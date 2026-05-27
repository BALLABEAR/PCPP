from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import shutil
import threading
from pathlib import Path
from typing import Any

import yaml


def _run_shell_command(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if int(completed.returncode) != 0:
        rendered = " ".join(command)
        raise RuntimeError(f"Native extension build failed in {cwd}: `{rendered}` (exit={completed.returncode}).")


def _ensure_native_extensions() -> None:
    payload_raw = str(os.getenv("PCPP_NATIVE_EXTENSIONS_JSON", "")).strip()
    if not payload_raw:
        return
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid PCPP_NATIVE_EXTENSIONS_JSON payload.") from exc
    if not isinstance(payload, list):
        raise RuntimeError("PCPP_NATIVE_EXTENSIONS_JSON must be a list.")
    os.environ.setdefault("TORCH_CUDA_ARCH_LIST", "8.6;8.9;9.0+PTX")

    rebuilt: list[str] = []
    extension_paths: list[str] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"native_extensions[{index}] must be an object.")

        module_dir_raw = str(item.get("module_dir") or "").strip()
        if not module_dir_raw:
            raise RuntimeError(f"native_extensions[{index}] has empty module_dir.")
        module_dir = Path(module_dir_raw)
        if not module_dir.is_absolute():
            module_dir = (Path("/app") / module_dir).resolve()
        else:
            module_dir = module_dir.resolve()
        if not module_dir.exists():
            raise RuntimeError(f"native_extensions[{index}] module_dir does not exist: {module_dir}")
        extension_paths.append(str(module_dir))

        so_glob = str(item.get("artifact_glob") or "*.so").strip() or "*.so"
        module_name = str(item.get("name") or module_dir.name).strip() or f"extension_{index}"

        if any(module_dir.glob(so_glob)):
            continue

        build_command = item.get("build")
        if isinstance(build_command, str):
            command = [chunk for chunk in shlex.split(build_command.strip()) if chunk]
        elif isinstance(build_command, list):
            command = [str(chunk).strip() for chunk in build_command if str(chunk).strip()]
        else:
            command = []
        if not command:
            command = ["python", "setup.py", "build_ext", "--inplace"]

        _run_shell_command(command, cwd=module_dir)
        if not any(module_dir.glob(so_glob)):
            raise RuntimeError(
                f"native_extensions[{index}] '{module_name}' did not produce artifacts matching '{so_glob}'."
            )
        rebuilt.append(module_name)

    if rebuilt:
        print("[training] Rebuilt native extensions: " + ", ".join(rebuilt), flush=True)
    if extension_paths:
        existing = str(os.getenv("PYTHONPATH", "")).strip()
        parts = [chunk for chunk in existing.split(":") if chunk] if existing else []
        parts.extend(extension_paths)
        dedup: list[str] = []
        seen: set[str] = set()
        for item in parts:
            if item in seen:
                continue
            seen.add(item)
            dedup.append(item)
        os.environ["PYTHONPATH"] = ":".join(dedup)


def _get_nested_value(payload: Any, dotted_path: str) -> Any:
    current = payload
    for raw_part in str(dotted_path or "").split("."):
        part = raw_part.strip()
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _set_nested_value(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    current: dict[str, Any] = payload
    parts = [part.strip() for part in str(dotted_path or "").split(".") if part.strip()]
    if not parts:
        return
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _apply_relative_finetune_horizon() -> None:
    if str(os.getenv("PCPP_TRAINING_MODE", "")).strip() != "finetune":
        return

    try:
        finetune_epochs = int(str(os.getenv("PCPP_FINETUNE_EPOCHS", "")).strip() or "0")
    except ValueError as exc:
        raise RuntimeError("Invalid PCPP_FINETUNE_EPOCHS value.") from exc
    if finetune_epochs <= 0:
        return

    contract = json.loads(str(os.getenv("PCPP_FINETUNE_CONTRACT_JSON", "{}")).strip() or "{}")
    checkpoint_epoch_path = str(contract.get("checkpoint_epoch_path") or "").strip()
    config_epoch_path = str(contract.get("config_epoch_path") or "").strip()
    epoch_target_mode = str(contract.get("epoch_target_mode") or "relative").strip().lower()
    config_resume_path = str(contract.get("config_resume_path") or "").strip()
    config_model_path = str(contract.get("config_model_path") or "").strip()
    config_eval_model_path = str(contract.get("config_eval_model_path") or "").strip()
    config_save_freq_path = str(contract.get("config_save_freq_path") or "").strip()
    checkpoint_path = str(os.getenv("PCPP_FINETUNE_CHECKPOINT_PATH", "")).strip()
    config_path = str(os.getenv("PCPP_FINETUNE_CONFIG_PATH", "")).strip()
    if not checkpoint_epoch_path or not config_epoch_path or not checkpoint_path or not config_path:
        return

    try:
        import torch

        checkpoint_payload = torch.load(checkpoint_path, map_location="cpu")
    except Exception as exc:
        raise RuntimeError(f"Failed to inspect finetune checkpoint inside training runtime: {checkpoint_path}") from exc

    checkpoint_epoch = _get_nested_value(checkpoint_payload, checkpoint_epoch_path)
    try:
        checkpoint_epoch_int = int(checkpoint_epoch)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Finetune checkpoint does not expose an integer epoch at '{checkpoint_epoch_path}'."
        ) from exc

    config_file = Path(config_path)
    config_payload = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if epoch_target_mode == "absolute":
        target_total_epochs = finetune_epochs
    else:
        target_total_epochs = checkpoint_epoch_int + finetune_epochs
    if target_total_epochs <= checkpoint_epoch_int:
        raise RuntimeError(
            "Finetune target epoch must be greater than checkpoint epoch. "
            f"checkpoint={checkpoint_epoch_int}, target={target_total_epochs}."
        )
    _set_nested_value(config_payload, config_epoch_path, target_total_epochs)
    if config_resume_path:
        _set_nested_value(config_payload, config_resume_path, True)
    if config_model_path:
        _set_nested_value(config_payload, config_model_path, checkpoint_path)
    if config_eval_model_path:
        _set_nested_value(config_payload, config_eval_model_path, checkpoint_path)
    if config_save_freq_path:
        _set_nested_value(config_payload, config_save_freq_path, 1)
    config_file.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")
    print(
        "[training] Finetune horizon adjusted: "
        f"{config_epoch_path}={target_total_epochs} "
        f"(checkpoint {checkpoint_epoch_path}={checkpoint_epoch_int}, mode={epoch_target_mode}, input={finetune_epochs})",
        flush=True,
    )
    print(
        "[training] Finetune config patched: "
        f"resume_path={config_resume_path or 'n/a'}; "
        f"model_path={config_model_path or 'n/a'}; "
        f"eval_model_path={config_eval_model_path or 'n/a'}; "
        f"save_freq_path={config_save_freq_path or 'n/a'}",
        flush=True,
    )


def _extract_flag_value(command: list[str], flag: str) -> str:
    for index, token in enumerate(command):
        if token == flag and index + 1 < len(command):
            return str(command[index + 1]).strip()
    return ""


def _remove_flag_with_value(command: list[str], flag: str) -> list[str]:
    output: list[str] = []
    skip_next = False
    for index, token in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if token == flag:
            if index + 1 < len(command):
                skip_next = True
            continue
        output.append(token)
    return output


def _prepare_finetune_resume_command(command: list[str]) -> list[str]:
    if str(os.getenv("PCPP_TRAINING_MODE", "")).strip() != "finetune":
        return command
    contract = json.loads(str(os.getenv("PCPP_FINETUNE_CONTRACT_JSON", "{}")).strip() or "{}")
    if not bool(contract.get("resume_via_experiment", False)):
        return command

    checkpoint_path = str(os.getenv("PCPP_FINETUNE_CHECKPOINT_PATH", "")).strip()
    if not checkpoint_path:
        return command
    checkpoint_file = Path(checkpoint_path)
    if not checkpoint_file.exists():
        raise RuntimeError(f"Finetune checkpoint not found for resume preparation: {checkpoint_file}")

    config_path_raw = _extract_flag_value(command, "--config")
    if not config_path_raw:
        return command
    config_file = Path(config_path_raw)
    if not config_file.exists():
        raise RuntimeError(f"Config file not found for resume preparation: {config_file}")

    exp_name = _extract_flag_value(command, "--exp_name") or "default"
    experiment_path = Path.cwd() / "experiments" / config_file.stem / config_file.parent.stem / exp_name
    experiment_path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_file, experiment_path / "config.yaml")
    shutil.copy2(checkpoint_file, experiment_path / "ckpt-last.pth")

    cli_checkpoint_arg = str(contract.get("cli_checkpoint_arg") or "").strip()
    prepared = list(command)
    if cli_checkpoint_arg:
        prepared = _remove_flag_with_value(prepared, cli_checkpoint_arg)
    cli_resume_arg = str(contract.get("cli_resume_arg") or "--resume").strip() or "--resume"
    if cli_resume_arg not in prepared:
        prepared.append(cli_resume_arg)
    print(f"[training] Finetune resume prepared in {experiment_path}.", flush=True)
    return prepared


def _ensure_unbuffered_python(command: list[str]) -> list[str]:
    if not command:
        return command
    executable = str(command[0]).strip().lower()
    python_like = executable in {"python", "python3"} or executable.endswith("/python") or executable.endswith("\\python")
    if not python_like:
        return command
    if "-u" in command[1:3]:
        return command
    return [command[0], "-u", *command[1:]]


def _run_streaming(command: list[str]) -> int:
    effective_command = _ensure_unbuffered_python(command)
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("TQDM_DISABLE", "0")
    env.setdefault("TQDM_MININTERVAL", "1")
    env.setdefault("TQDM_MINITERS", "1")
    process = subprocess.Popen(
        effective_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=env,
    )
    assert process.stdout is not None

    stop_heartbeat = threading.Event()

    def _heartbeat_worker() -> None:
        while not stop_heartbeat.wait(30.0):
            print("[training] still running...", flush=True)

    heartbeat_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
    heartbeat_thread.start()

    try:
        buffer = b""
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            while True:
                nl_index = buffer.find(b"\n")
                cr_index = buffer.find(b"\r")
                indexes = [idx for idx in (nl_index, cr_index) if idx >= 0]
                if not indexes:
                    break
                split_at = min(indexes)
                line = buffer[:split_at]
                buffer = buffer[split_at + 1 :]
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    print(text, flush=True)
        tail = buffer.decode("utf-8", errors="replace").strip()
        if tail:
            print(tail, flush=True)
        return int(process.wait())
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1.0)


def main() -> int:
    if len(sys.argv) < 2:
        print("[training-error] launch_training.py requires a command to execute.", file=sys.stderr, flush=True)
        return 2
    _ensure_native_extensions()
    _apply_relative_finetune_horizon()
    return _run_streaming(_prepare_finetune_resume_command(list(sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
