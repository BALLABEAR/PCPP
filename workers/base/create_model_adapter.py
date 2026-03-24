import argparse
from pathlib import Path


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _worker_template(task_type: str, model_id: str) -> str:
    class_name = "".join(part.capitalize() for part in model_id.split("_")) + "Worker"
    return f"""import argparse
import shutil
from pathlib import Path

from workers.base.base_worker import BaseWorker


class {class_name}(BaseWorker):
    \"\"\"Auto-generated adapter template. Replace process() with real inference.\"\"\"

    def __init__(self) -> None:
        super().__init__(model_id="{model_id}")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_path = output_dir / f"{{input_path.stem}}_{model_id}{{input_path.suffix or '.bin'}}"
        shutil.copy2(input_path, output_path)
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="PCPP generated worker template")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    worker = {class_name}()
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
gpu_required: true
batching_mode: disabled
github_url: {repo_path}
params:
  mode:
    type: str
    default: default
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
    return f"""FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel pyyaml

COPY workers/base/runtime /app/workers/base/runtime
COPY {manifest_path} /app/runtime.manifest.yaml
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase system
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase python

COPY workers /app/workers
COPY external_models /app/external_models
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
    _write_if_missing(target / "worker.py", _worker_template(args.task_type, args.model_id))
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
                "1. Implement real inference in worker.py",
                "2. Fill runtime.manifest.yaml with exact deps/build steps",
                "3. Validate with examples/run_model_docker.ps1 or .sh",
            ]
        )
        + "\n",
    )

    print(f"Adapter scaffold is ready: {target}")


if __name__ == "__main__":
    main()
