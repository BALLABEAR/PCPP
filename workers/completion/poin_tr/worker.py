import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from workers.base.base_worker import BaseWorker


class PoinTrWorker(BaseWorker):
    """Auto-generated adapter with fail-fast entry command."""

    def __init__(self) -> None:
        super().__init__(model_id="poin_tr")
        self.repo_path = "./external_models/PoinTr"
        self.entry_command = "python {repo_path}/tools/inference.py {config_path} {weights_path} --pc {input} --out_pc_root {output_dir} --device {device}"
        self.weights_path = "./external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth"
        self.config_path = "./external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml"
        self.cli_overrides: dict[str, str] = {}

    def process(self, input_path: Path, output_dir: Path) -> Path:
        if not self.entry_command.strip():
            raise RuntimeError(
                "entry_command is empty in generated adapter. "
                "Provide entry_command in onboarding Advanced fields."
            )
        overrides = self.cli_overrides or {}
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
                return f"/app/{value}"
            if value.startswith(repo_name + "/"):
                return f"/app/external_models/{value}"
            return value
        resolved_weights = _to_container_path(resolved_weights)
        resolved_config = _to_container_path(resolved_config)
        # Copy input under output_dir and pass a basename-only path for {input}.
        # Many upstream CLIs join(output_root, stem(input_path)); if input_path is absolute,
        # os.path.join drops output_root and writes outside output_dir (e.g. PoinTr inference.py).
        run_cwd = in_repo if in_repo.exists() else output_dir
        staged_dir = run_cwd / ".pcpp_tmp_inputs"
        staged_dir.mkdir(parents=True, exist_ok=True)
        staged = staged_dir / f"_pcpp_input{input_path.suffix}"
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
                f"Unsupported placeholder in entry_command: {exc}. "
                "Allowed placeholders: {input}, {output_dir}, {repo_path}, "
                "{weights_path}, {config_path}, {device}, {mode}."
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
                f"entry_command failed (exit={result.returncode})\n"
                f"CMD: {command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        produced = [p for p in output_dir.rglob("*") if p.is_file()]
        if not produced:
            raise RuntimeError(
                "entry_command completed but no files were produced in output_dir. "
                "Use {output_dir} placeholder in entry_command."
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

    worker = PoinTrWorker()
    if unknown:
        raise RuntimeError(
            f"Unknown worker arguments: {unknown}. "
            "Use supported overrides: --repo-path --weights-path/--weights --config-path/--config --device --mode."
        )
    overrides = {
        "repo_path": args.repo_path,
        "weights_path": args.weights_path,
        "config_path": args.config_path,
        "device": args.device,
        "mode": args.mode,
    }
    worker.cli_overrides = overrides
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
