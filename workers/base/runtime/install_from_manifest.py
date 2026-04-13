import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
import shlex


def _run(command: str) -> None:
    retries = int(os.getenv("RUNTIME_CMD_RETRIES", "3"))
    retry_delay = int(os.getenv("RUNTIME_CMD_RETRY_DELAY_SEC", "10"))
    last_error: subprocess.CalledProcessError | None = None

    for attempt in range(1, retries + 1):
        print(f"[runtime-manifest] (attempt {attempt}/{retries}) {command}")
        try:
            subprocess.run(command, shell=True, check=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < retries:
                print(
                    f"[runtime-manifest] command failed (exit={exc.returncode}); "
                    f"retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                break

    assert last_error is not None
    raise last_error


def _load_manifest(path: Path) -> dict:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required. Install with: python -m pip install pyyaml") from exc

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Manifest root must be a mapping")
    return payload


def _apply_env(manifest: dict) -> None:
    for key, value in (manifest.get("env") or {}).items():
        os.environ[str(key)] = str(value)


def _run_system_phase(manifest: dict) -> None:
    packages = manifest.get("system_packages") or []
    if packages:
        joined = " ".join(packages)
        _run("apt-get update")
        _run(f"apt-get install -y --no-install-recommends {joined}")
        _run("rm -rf /var/lib/apt/lists/*")


def _run_python_phase(manifest: dict) -> None:
    python_section = manifest.get("python") or {}

    # Run explicit commands first so pinned/install-indexed deps (e.g. torch CUDA wheels)
    # are present before generic package installation resolves transitive requirements.
    for command in python_section.get("pip_commands") or []:
        _run(command)

    pip_packages = python_section.get("pip") or []
    pip_extra_args = " ".join(python_section.get("pip_extra_args") or [])
    if pip_packages:
        # Shell-escape package specs like numpy<2, torch==2.1.2+cu118, etc.
        joined = " ".join(shlex.quote(str(item)) for item in pip_packages)
        command = f"python -m pip install --no-cache-dir {pip_extra_args} {joined}".strip()
        _run(command)

    for req_file in python_section.get("pip_requirements_files") or []:
        _run(f"python -m pip install --no-cache-dir -r {req_file}")


def _run_build_phase(manifest: dict) -> None:
    for command in manifest.get("build_steps") or []:
        _run(command)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install runtime dependencies from runtime.manifest.yaml")
    parser.add_argument("--manifest", required=True, help="Path to runtime.manifest.yaml")
    parser.add_argument("--phase", required=True, choices=["system", "python", "build"])
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = _load_manifest(manifest_path)
    _apply_env(manifest)

    if args.phase == "system":
        _run_system_phase(manifest)
    elif args.phase == "python":
        _run_python_phase(manifest)
    elif args.phase == "build":
        _run_build_phase(manifest)
    else:
        raise ValueError(f"Unsupported phase: {args.phase}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Manifest installation failed: {exc}", file=sys.stderr)
        raise
