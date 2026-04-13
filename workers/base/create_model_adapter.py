import argparse
import shlex
import subprocess
import os
from pathlib import Path


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _worker_template(task_type: str, model_id: str, repo_path: str, entry_command: str, weights_path: str, config_path: str) -> str:
    class_name = "".join(part.capitalize() for part in model_id.split("_")) + "Worker"
    return f"""import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from workers.base.base_worker import BaseWorker


class {class_name}(BaseWorker):
    \"\"\"Auto-generated adapter with fail-fast entry command.\"\"\"

    def __init__(self) -> None:
        super().__init__(model_id="{model_id}")
        self.repo_path = "{repo_path}"
        self.entry_command = "{entry_command}"
        self.weights_path = "{weights_path}"
        self.config_path = "{config_path}"
        self.cli_overrides: dict[str, str] = {{}}

    def process(self, input_path: Path, output_dir: Path) -> Path:
        if not self.entry_command.strip():
            raise RuntimeError(
                "entry_command is empty in generated adapter. "
                "Provide entry_command in onboarding Advanced fields."
            )
        overrides = self.cli_overrides or {{}}
        resolved_repo_path = overrides.get("repo_path") or self.repo_path
        repo_name = Path(str(resolved_repo_path)).name
        in_repo = Path("/app/external_models") / repo_name
        resolved_weights = overrides.get("weights_path") or self.weights_path
        resolved_config = overrides.get("config_path") or self.config_path
        resolved_device = overrides.get("device") or "cuda:0"
        resolved_mode = overrides.get("mode") or "model"
        def _to_container_path(raw: str) -> str:
            value = str(raw or "").strip()
            if not value:
                return value
            if value.startswith("/app/"):
                return value
            if value.startswith("./"):
                value = value[2:]
            if value.startswith("external_models/"):
                return f"/app/{{value}}"
            if value.startswith(repo_name + "/"):
                return f"/app/external_models/{{value}}"
            return value
        resolved_weights = _to_container_path(resolved_weights)
        resolved_config = _to_container_path(resolved_config)
        # Copy input under output_dir and pass a basename-only path for {{input}}.
        # Many upstream CLIs join(output_root, stem(input_path)); if input_path is absolute,
        # os.path.join drops output_root and writes outside output_dir (e.g. PoinTr inference.py).
        run_cwd = in_repo if in_repo.exists() else output_dir
        staged_dir = run_cwd / ".pcpp_tmp_inputs"
        staged_dir.mkdir(parents=True, exist_ok=True)
        staged = staged_dir / f"_pcpp_input{{input_path.suffix}}"
        shutil.copy2(input_path, staged)
        input_rel = str(staged.relative_to(run_cwd))
        try:
            command = self.entry_command.format(
                input=input_rel,
                output_dir=str(output_dir),
                repo_path=str(in_repo),
                weights_path=resolved_weights,
                config_path=resolved_config,
                device=resolved_device,
                mode=resolved_mode,
            )
        except KeyError as exc:
            raise RuntimeError(
                f"Unsupported placeholder in entry_command: {{exc}}. "
                "Allowed placeholders: {{input}}, {{output_dir}}, {{repo_path}}, "
                "{{weights_path}}, {{config_path}}, {{device}}, {{mode}}."
            ) from exc
        result = subprocess.run(
            shlex.split(command),
            cwd=str(run_cwd),
            env=self._runtime_env(in_repo),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"entry_command failed (exit={{result.returncode}})\\n"
                f"CMD: {{command}}\\nSTDOUT:\\n{{result.stdout}}\\nSTDERR:\\n{{result.stderr}}"
            )
        produced = [p for p in output_dir.rglob("*") if p.is_file()]
        if not produced:
            raise RuntimeError(
                "entry_command completed but no files were produced in output_dir. "
                "Use {{output_dir}} placeholder in entry_command."
            )
        return max(produced, key=lambda p: p.stat().st_mtime)

    def _runtime_env(self, in_repo: Path) -> dict[str, str]:
        env = dict(os.environ)
        py_path_parts: list[str] = []
        current = env.get("PYTHONPATH", "")
        if current:
            py_path_parts.extend([p for p in current.split(":") if p])
        py_path_parts.append("/app")
        ext_root = in_repo / "extensions"
        if ext_root.exists() and ext_root.is_dir():
            for child in ext_root.iterdir():
                if child.is_dir():
                    py_path_parts.append(str(child))
        # Preserve order and remove duplicates.
        seen: set[str] = set()
        normalized: list[str] = []
        for item in py_path_parts:
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        env["PYTHONPATH"] = ":".join(normalized)
        return env


def main() -> None:
    parser = argparse.ArgumentParser(description="PCPP generated worker template")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--repo-path", "--repo_path", dest="repo_path", default="", help="Optional repo override")
    parser.add_argument("--weights", "--weights-path", "--weights_path", dest="weights_path", default="", help="Optional weights override")
    parser.add_argument("--config", "--config-path", "--config_path", dest="config_path", default="", help="Optional config override")
    parser.add_argument("--device", default="", help="Optional device override")
    parser.add_argument("--mode", default="", help="Optional mode override")
    args, unknown = parser.parse_known_args()

    worker = {class_name}()
    if unknown:
        raise RuntimeError(
            f"Unknown worker arguments: {{unknown}}. "
            "Use supported overrides: --repo-path --weights-path/--weights --config-path/--config --device --mode."
        )
    overrides = {{
        "repo_path": args.repo_path,
        "weights_path": args.weights_path,
        "config_path": args.config_path,
        "device": args.device,
        "mode": args.mode,
    }}
    worker.cli_overrides = overrides
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
"""


def _model_card_template(
    model_id: str,
    task_type: str,
    input_formats: list[str],
    output_formats: list[str],
    repo_path: str,
    description: str,
) -> str:
    in_fmt = ", ".join(input_formats)
    out_fmt = ", ".join(output_formats)
    return f"""id: {model_id}
name: {model_id}
task_type: {task_type}
description: >
  {description}
input_format: [{in_fmt}]
output_format: [{out_fmt}]
accepted_input_formats: [{in_fmt}]
produced_output_formats: [{out_fmt}]
preferred_output_format: {output_formats[0] if output_formats else '.xyz'}
gpu_required: true
batching_mode: disabled
github_url: {repo_path}
params:
  repo_path:
    type: path
    required: false
    aliases: [repo-path, repo]
    description: optional repository override mounted under /app/external_models
  weights_path:
    type: path
    required: false
    aliases: [weights, weights-path]
    description: model checkpoint path
  config_path:
    type: path
    required: false
    aliases: [config, config-path]
    description: model config path
  device:
    type: str
    required: false
    aliases: []
    description: execution device, e.g. cuda:0 or cpu
  mode:
    type: str
    required: false
    aliases: []
    default: model
    description: runtime mode of the model adapter
"""


def _manifest_template() -> str:
    return """version: 1
base_image: nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04
system_packages:
  - python3
  - python3-pip
  - python3-dev
  - build-essential
  - git
python:
  pip_commands:
    - python -m pip install --no-cache-dir --upgrade pip setuptools wheel
    - python -m pip install --no-cache-dir pyyaml
build_steps: []
env:
  PYTHONUNBUFFERED: "1"
"""


def _dockerfile_template(task_type: str, model_id: str) -> str:
    module_path = f"workers.{task_type}.{model_id}.worker"
    manifest_path = f"workers/{task_type}/{model_id}/runtime.manifest.yaml"
    return f"""FROM pcpp-runtime-cuda118:latest

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN if ! command -v python >/dev/null 2>&1; then \
      apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*; \
      ln -sf /usr/bin/python3 /usr/bin/python; \
    fi
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel pyyaml

COPY workers/base/runtime /app/workers/base/runtime
COPY {manifest_path} /app/runtime.manifest.yaml
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase system
COPY external_models /app/external_models
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase python

COPY workers /app/workers
ENV PYTHONPATH=/app

RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase build

CMD ["python", "-m", "{module_path}", "--help"]
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PCPP model adapter scaffold")
    parser.add_argument("--task-type", required=True, help="Task type folder name, e.g. completion/meshing/segmentation")
    parser.add_argument("--model-id", required=True, help="Model id / folder name, e.g. shape_as_points")
    parser.add_argument("--repo-path", required=True, help="Source repo URL or local path")
    parser.add_argument("--entry-command", default="", help="Original repo entry command (for reference)")
    parser.add_argument("--weights-path", default="", help="Weights path used for templated entry command")
    parser.add_argument("--config-path", default="", help="Config path used for templated entry command")
    parser.add_argument("--input-format", default=".xyz", help="Comma-separated input formats")
    parser.add_argument("--output-format", default=".xyz", help="Comma-separated output formats")
    parser.add_argument(
        "--description",
        default="Generated adapter scaffold. Replace template logic with real inference.",
        help="Short model description",
    )
    args = parser.parse_args()

    root = Path.cwd()
    target = root / "workers" / args.task_type / args.model_id
    input_formats = [item.strip() for item in args.input_format.split(",") if item.strip()]
    output_formats = [item.strip() for item in args.output_format.split(",") if item.strip()]
    if not input_formats:
        input_formats = [".xyz"]
    if not output_formats:
        output_formats = [".xyz"]

    _write_if_missing(target / "__init__.py", "# Generated model adapter package.\n")
    _write_if_missing(
        target / "worker.py",
        _worker_template(
            args.task_type,
            args.model_id,
            args.repo_path,
            args.entry_command,
            args.weights_path,
            args.config_path,
        ),
    )
    _write_if_missing(
        target / "model_card.yaml",
        _model_card_template(
            model_id=args.model_id,
            task_type=args.task_type,
            input_formats=input_formats,
            output_formats=output_formats,
            repo_path=args.repo_path,
            description=args.description,
        ),
    )
    _write_if_missing(target / "runtime.manifest.yaml", _manifest_template())
    _write_if_missing(target / "Dockerfile", _dockerfile_template(args.task_type, args.model_id))

    readme = target / "README.generated.md"
    _write_if_missing(
        readme,
        "\n".join(
            [
                "# Generated adapter notes",
                "",
                f"- entry-command (source): `{args.entry_command or 'not provided'}`",
                f"- repo-path: `{args.repo_path}`",
                "",
                "Next steps:",
                "1. Verify entry_command placeholders and repo paths",
                "2. Fill runtime.manifest.yaml with exact deps/build steps",
                "3. Validate with onboarding build/smoke flow",
            ]
        )
        + "\n",
    )

    print(f"Adapter scaffold is ready: {target}")


if __name__ == "__main__":
    main()
