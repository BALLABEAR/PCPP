from __future__ import annotations

import json
import shlex
from pathlib import Path

from app.model_onboarding.schemas import ModelPayload


# Создает папку worker и шаблонные файлы для выбранной модели
def scaffold_model_files(payload: ModelPayload, workspace_root: Path) -> Path:
    target_dir = workspace_root / "workers" / payload.task_type / payload.model_id
    if target_dir.exists():
        raise FileExistsError(f"Worker directory already exists: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=False)
    _write_worker_file(target_dir, payload)
    _write_runtime_manifest(target_dir, payload)
    _write_model_card(target_dir, payload)
    _write_dockerfile(target_dir, payload)
    return target_dir


# Записывает шаблонный worker.py для модели
def _write_worker_file(target_dir: Path, payload: ModelPayload) -> None:
    template_path = Path(__file__).parent / "templates" / "worker.py.tpl"
    text = template_path.read_text(encoding="utf-8").replace("{{model_id}}", payload.model_id)
    (target_dir / "worker.py").write_text(text, encoding="utf-8")


# Генерирует Dockerfile из шаблона и advanced-полей
def _write_dockerfile(target_dir: Path, payload: ModelPayload) -> None:
    template_path = Path(__file__).parent / "templates" / "Dockerfile.tpl"
    base_image = payload.base_image or "python:3.11-slim"
    text = (
        template_path.read_text(encoding="utf-8")
        .replace("{{base_image}}", base_image)
        .replace("{{system_packages_block}}", _build_system_packages_block(payload))
        .replace("{{pip_install_block}}", _build_pip_install_block(payload))
        .replace("{{env_block}}", _build_env_block(payload))
        .replace("{{build_steps_block}}", _build_build_steps_block(payload))
        .replace("{{repo_path}}", _normalize_relative_path(payload.repo_path))
        .replace("{{task_type}}", payload.task_type)
        .replace("{{model_id}}", payload.model_id)
    )
    (target_dir / "Dockerfile").write_text(text, encoding="utf-8")


# Записывает runtime.manifest.yaml с настройками запуска и сборки
def _write_runtime_manifest(target_dir: Path, payload: ModelPayload) -> None:
    text = (
        f"model_id: {payload.model_id}\n"
        f"task_type: {payload.task_type}\n"
        f"entry_command: {payload.entry_command or 'python worker.py'}\n"
        f"base_image: {payload.base_image}\n"
        f"extra_pip_packages: {json.dumps(_split_lines(payload.extra_pip_packages))}\n"
        f"pip_requirements_files: {json.dumps(_split_lines(payload.pip_requirements_files))}\n"
        f"pip_extra_args: {json.dumps(_split_lines(payload.pip_extra_args))}\n"
        f"system_packages: {json.dumps(_split_lines(payload.system_packages))}\n"
        f"extra_build_steps: {json.dumps(_split_lines(payload.extra_build_steps))}\n"
        f"env_overrides: {json.dumps(_split_env(payload.env_overrides))}\n"
        f"smoke_args: {json.dumps(_split_lines(payload.smoke_args))}\n"
    )
    (target_dir / "runtime.manifest.yaml").write_text(text, encoding="utf-8")


# Записывает карточку модели для generated worker
def _write_model_card(target_dir: Path, payload: ModelPayload) -> None:
    text = (
        f"id: {payload.model_id}\n"
        f"name: {payload.model_id}\n"
        f"task_type: {payload.task_type}\n"
        f"repo_path: {payload.repo_path}\n"
        f"weights_path: {payload.weights_path}\n"
        f"config_path: {payload.config_path}\n"
    )
    (target_dir / "model_card.yaml").write_text(text, encoding="utf-8")


# Разбивает многострочное поле на список непустых строк
def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


# Разбирает env overrides из KEY=VALUE в словарь
def _split_env(value: str) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for line in _split_lines(value):
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        env_map[key.strip()] = raw_val.strip()
    return env_map


# Формирует RUN-блок для установки системных пакетов
def _build_system_packages_block(payload: ModelPayload) -> str:
    packages = _split_lines(payload.system_packages)
    if not packages:
        return ""
    return (
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        f"{' '.join(shlex.quote(item) for item in packages)}"
        " && rm -rf /var/lib/apt/lists/*"
    )


# Формирует RUN-блоки для pip install из advanced-настроек
def _build_pip_install_block(payload: ModelPayload) -> str:
    commands: list[str] = ["RUN python -m pip install --upgrade pip"]
    extra_args = " ".join(shlex.quote(item) for item in _split_lines(payload.pip_extra_args))
    requirements = _split_lines(payload.pip_requirements_files)
    if requirements:
        normalized = [_normalize_relative_path(payload.repo_path, item) for item in requirements]
        req_flags = " ".join(f"-r /workspace/{path}" for path in normalized)
        suffix = f" {extra_args}" if extra_args else ""
        commands.append(f"RUN python -m pip install{suffix} {req_flags}".rstrip())
    packages = _split_lines(payload.extra_pip_packages)
    if packages:
        suffix = f" {extra_args}" if extra_args else ""
        pkg_values = " ".join(shlex.quote(item) for item in packages)
        commands.append(f"RUN python -m pip install{suffix} {pkg_values}".rstrip())
    return "\n".join(commands)


# Формирует ENV-блок для Dockerfile
def _build_env_block(payload: ModelPayload) -> str:
    env_map = _split_env(payload.env_overrides)
    if not env_map:
        return ""
    lines = [f"ENV {key}={json.dumps(value)}" for key, value in env_map.items()]
    return "\n".join(lines)


# Формирует RUN-блоки для дополнительных build steps
def _build_build_steps_block(payload: ModelPayload) -> str:
    steps = _split_lines(payload.extra_build_steps)
    if not steps:
        return ""
    return "\n".join(f"RUN {step}" for step in steps)


# Нормализует относительный путь для использования в scaffold
def _normalize_relative_path(base_path: str, child_path: str = "") -> str:
    parts = [part.strip().replace("\\", "/") for part in (base_path, child_path) if part.strip()]
    joined = "/".join(parts)
    while joined.startswith("./"):
        joined = joined[2:]
    return joined.strip("/")
