from __future__ import annotations

import re
import shlex
import subprocess
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_workspace_root
from app.core.db import SessionLocal
from app.model_onboarding import repository
from app.model_onboarding.scaffold.generator import scaffold_model_files
from app.model_onboarding.schemas import ModelPayload, RunResponse, StageState
from app.model_onboarding.stage_runner import append_log, set_stage, to_stage_state

# Реализует бизнес-логику onboarding: validate, scaffold, build, smoke и registry.


# Проверяет payload модели и возвращает valid/errors/warnings.
def validate_model_payload(payload: ModelPayload) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_required_fields(payload, errors)
    _validate_model_id(payload.model_id, errors)
    _validate_enums(payload, errors)
    _validate_paths(payload, errors, warnings)
    return len(errors) == 0, errors, warnings


# Создает единый onboarding-run и запускает асинхронный пайплайн validate->scaffold->build->smoke->registry.
def run_scaffold_pipeline(db: Session, payload: ModelPayload) -> RunResponse:
    existing = repository.find_active_model(db, payload.model_id)
    if existing is not None:
        return _duplicate_model_response(payload.model_id)

    run = repository.create_run(db, payload.model_id)
    run.status = "running"
    set_stage(run, "validate", "running")
    append_log(run, "[run] onboarding started")
    db.commit()
    db.refresh(run)

    thread = threading.Thread(
        target=_onboarding_worker_thread,
        kwargs={
            "run_id": run.id,
            "payload_data": payload.model_dump(by_alias=True),
        },
        daemon=True,
    )
    thread.start()
    return _to_run_response(run)


# Возвращает текущее состояние запуска onboarding.
def get_run_response(db: Session, run_id: str) -> RunResponse | None:
    run = repository.get_run(db, run_id)
    if run is None:
        return None
    return _to_run_response(run)


# Формирует стандартный ответ при попытке зарегистрировать существующую модель.
def _duplicate_model_response(model_id: str) -> RunResponse:
    return RunResponse(
        run_id="",
        model_id=model_id,
        status="failed",
        stages=StageState(validate="pending", scaffold="pending", build="pending", smoke="pending", registry="pending"),
        logs="",
        error_message=f"Model '{model_id}' already exists.",
        created_at=None,
        updated_at=None,
    )


# Проверяет обязательные поля payload.
def _validate_required_fields(payload: ModelPayload, errors: list[str]) -> None:
    required_fields = [
        ("task_type", payload.task_type),
        ("model_id", payload.model_id),
        ("repo_path", payload.repo_path),
        ("weights_path", payload.weights_path),
        ("config_path", payload.config_path),
        ("smoke_input_path", payload.smoke_input_path),
    ]
    for field_name, value in required_fields:
        if not str(value or "").strip():
            errors.append(f"Field '{field_name}' is required.")


# Проверяет формат model_id.
def _validate_model_id(model_id: str, errors: list[str]) -> None:
    if not re.fullmatch(r"[a-z0-9_\-]+", str(model_id or "").strip()):
        errors.append("Field 'model_id' must match [a-z0-9_-]+.")


# Проверяет допустимые enum-значения payload.
def _validate_enums(payload: ModelPayload, errors: list[str]) -> None:
    allowed_tasks = {"completion", "meshing", "upsampling"}
    if payload.task_type not in allowed_tasks:
        errors.append("Field 'task_type' must be one of: completion, meshing, upsampling.")


# Проверяет базовые ограничения для путей, включая существование файлов внутри workspace.
def _validate_paths(payload: ModelPayload, errors: list[str], warnings: list[str]) -> None:
    for field_name in ("repo_path", "weights_path", "config_path", "smoke_input_path"):
        value = str(getattr(payload, field_name) or "")
        if "\\" in value:
            warnings.append(f"Field '{field_name}' contains backslashes; use '/' for portability.")
        if ".." in value:
            errors.append(f"Field '{field_name}' must not contain '..'.")

    workspace_root = Path(get_workspace_root()).resolve()
    repo_path = _resolve_workspace_path(workspace_root, payload.repo_path)
    weights_path = _resolve_workspace_path(workspace_root, payload.weights_path)
    config_path = _resolve_workspace_path(workspace_root, payload.config_path)
    smoke_input_path = _resolve_workspace_path(workspace_root, payload.smoke_input_path)

    if not repo_path.is_dir():
        errors.append(f"Field 'repo_path' must point to an existing directory: {repo_path}")
    if not weights_path.exists():
        errors.append(f"Field 'weights_path' must point to an existing file: {weights_path}")
    if not config_path.exists():
        errors.append(f"Field 'config_path' must point to an existing file or directory: {config_path}")
    if not smoke_input_path.is_file():
        errors.append(f"Field 'smoke_input_path' must point to an existing file: {smoke_input_path}")


# Добавляет все предупреждения в лог запуска.
def _append_warnings(run, warnings: list[str]) -> None:
    for item in warnings:
        append_log(run, f"[validate-warning] {item}")


# Преобразует ORM-запись запуска в API-ответ.
def _to_run_response(run) -> RunResponse:
    return RunResponse(
        run_id=run.id,
        model_id=run.model_id,
        status=run.status,
        stages=to_stage_state(run),
        logs=run.logs,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


# Выполняет полный onboarding-пайплайн в фоне и пишет стадии/логи в один run.
def _onboarding_worker_thread(*, run_id: str, payload_data: dict[str, str]) -> None:
    db = SessionLocal()
    try:
        run = repository.get_run_or_none(db, run_id)
        if run is None:
            return

        payload = ModelPayload.model_validate(payload_data)
        valid, errors, warnings = validate_model_payload(payload)
        if not valid:
            _fail_run(run, "validate", "; ".join(errors), f"[validate] failed: {'; '.join(errors)}")
            _append_warnings(run, warnings)
            db.commit()
            return

        set_stage(run, "validate", "success")
        append_log(run, "[validate] success")
        _append_warnings(run, warnings)
        set_stage(run, "scaffold", "running")
        db.commit()

        workspace_root = Path(get_workspace_root()).resolve()
        try:
            target_dir = scaffold_model_files(payload, workspace_root=workspace_root)
        except FileExistsError as exc:
            _fail_run(run, "scaffold", str(exc), f"[scaffold] failed: {exc}")
            db.commit()
            return

        set_stage(run, "scaffold", "success")
        append_log(run, f"[scaffold] success: {target_dir}")
        set_stage(run, "build", "running")
        db.commit()

        build_ok, build_error = _execute_build(run_id=run.id, task_type=payload.task_type, model_id=payload.model_id)
        run = repository.get_run_or_none(db, run_id)
        if run is None:
            return
        if not build_ok:
            _fail_run(run, "build", build_error or "Build failed.", f"[build] failed: {build_error or 'Build failed.'}")
            db.commit()
            return

        set_stage(run, "build", "success")
        append_log(run, "[build] success")
        set_stage(run, "smoke", "running")
        db.commit()

        smoke_ok, smoke_error = _execute_smoke(run_id=run.id, payload=payload)
        run = repository.get_run_or_none(db, run_id)
        if run is None:
            return
        if not smoke_ok:
            _fail_run(run, "smoke", smoke_error or "Smoke failed.", f"[smoke] failed: {smoke_error or 'Smoke failed.'}")
            db.commit()
            return

        set_stage(run, "smoke", "success")
        append_log(run, "[smoke] success")
        set_stage(run, "registry", "running")
        db.commit()

        try:
            repository.save_model_card(db, payload)
        except Exception as exc:
            _fail_run(run, "registry", f"Registry save failed: {exc}", f"[registry] failed: {exc}")
            db.commit()
            return

        set_stage(run, "registry", "success")
        run.status = "success"
        run.error_message = None
        append_log(run, "[registry] success")
        db.commit()
    except Exception as exc:
        run = repository.get_run_or_none(db, run_id)
        if run is None:
            return
        run.status = "failed"
        run.error_message = f"Onboarding crashed: {exc}"
        append_log(run, f"[run] failed: {exc}")
        db.commit()
    finally:
        db.close()


# Помечает текущий этап как failed и завершает run ошибкой.
def _fail_run(run, stage_name: str, error_message: str, log_line: str) -> None:
    set_stage(run, stage_name, "failed")
    run.status = "failed"
    run.error_message = error_message
    append_log(run, log_line)


# Запускает docker build и стримит stdout/stderr в лог запуска.
def _execute_build(*, run_id: str, task_type: str, model_id: str) -> tuple[bool, str | None]:
    workspace_root = Path(get_workspace_root()).resolve()
    target_dir = (workspace_root / "workers" / task_type / model_id).resolve()
    dockerfile_path = target_dir / "Dockerfile"
    runtime_manifest_path = target_dir / "runtime.manifest.yaml"
    worker_path = target_dir / "worker.py"

    missing = [
        str(path)
        for path in (target_dir, dockerfile_path, runtime_manifest_path, worker_path)
        if not path.exists()
    ]
    if missing:
        return False, f"Build cannot start: scaffold files are missing: {', '.join(missing)}"

    image_tag = _build_image_tag(task_type, model_id)
    command = [
        "docker",
        "build",
        "-t",
        image_tag,
        "-f",
        str(dockerfile_path),
        str(workspace_root),
    ]
    return _stream_process(run_id=run_id, command=command, log_prefix="[docker]")


# Запускает smoke-контейнер и стримит stdout/stderr в лог запуска.
def _execute_smoke(*, run_id: str, payload: ModelPayload) -> tuple[bool, str | None]:
    workspace_root = Path(get_workspace_root()).resolve()
    repo_path = _resolve_workspace_path(workspace_root, payload.repo_path)
    smoke_input_path = _resolve_workspace_path(workspace_root, payload.smoke_input_path)
    if not repo_path.exists():
        return False, f"Smoke cannot start: repo_path does not exist: {repo_path}"
    if not smoke_input_path.exists():
        return False, f"Smoke cannot start: smoke_input_path does not exist: {smoke_input_path}"

    image_tag = _build_image_tag(payload.task_type, payload.model_id)
    workdir = f"/workspace/{_normalize_container_path(payload.repo_path)}"
    smoke_input_container = f"/workspace/{_normalize_container_path(payload.smoke_input_path)}"
    smoke_command = _build_smoke_command(payload, smoke_input_container)
    command = ["docker", "run", "--rm", "--workdir", workdir]
    for key, value in _parse_env_overrides(payload.env_overrides).items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([image_tag, "sh", "-lc", smoke_command])
    return _stream_process(run_id=run_id, command=command, log_prefix="[smoke]")


# Формирует shell-команду smoke для entry_command и smoke_args.
def _build_smoke_command(payload: ModelPayload, smoke_input_container: str) -> str:
    worker_command = (
        f"python /workspace/workers/{payload.task_type}/{payload.model_id}/worker.py "
        f"{shlex.quote(smoke_input_container)} /tmp/pcpp_smoke_output"
    )
    base_command = payload.entry_command.strip() or worker_command
    base_command = base_command.replace("{smoke_input_path}", shlex.quote(smoke_input_container))
    base_command = base_command.replace("{workspace_root}", "/workspace")
    smoke_args = payload.smoke_args.strip()
    if smoke_args:
        rendered_args = smoke_args.replace("{smoke_input_path}", shlex.quote(smoke_input_container))
        rendered_args = rendered_args.replace("{workspace_root}", "/workspace")
        return f"{base_command} {rendered_args}".strip()
    return f"{base_command} {shlex.quote(smoke_input_container)}".strip() if payload.entry_command.strip() else base_command


# Выполняет внешний процесс и пишет его stdout/stderr в лог указанного run.
def _stream_process(*, run_id: str, command: list[str], log_prefix: str) -> tuple[bool, str | None]:
    _append_runtime_log(run_id, f"{log_prefix} command: {' '.join(command)}")
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return False, "Docker CLI is not available in orchestrator runtime."

    assert process.stdout is not None
    for line in process.stdout:
        _append_runtime_log(run_id, f"{log_prefix} {line.rstrip()}")
    exit_code = process.wait()
    if exit_code == 0:
        return True, None
    return False, f"Process failed with exit code {exit_code}."


# Добавляет runtime-лог в run через отдельную краткоживущую DB-сессию.
def _append_runtime_log(run_id: str, line: str) -> None:
    db = SessionLocal()
    try:
        run = repository.get_run_or_none(db, run_id)
        if run is None:
            return
        append_log(run, line)
        db.commit()
    finally:
        db.close()


# Преобразует относительный путь из payload в абсолютный путь внутри workspace.
def _resolve_workspace_path(workspace_root: Path, raw_path: str) -> Path:
    normalized = str(raw_path or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return (workspace_root / normalized).resolve()


# Нормализует путь для использования внутри контейнера.
def _normalize_container_path(raw_path: str) -> str:
    normalized = str(raw_path or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


# Возвращает docker image tag для модели.
def _build_image_tag(task_type: str, model_id: str) -> str:
    return f"pcpp-{task_type}-{model_id}:gpu"


# Разбирает env_overrides из текста в словарь.
def _parse_env_overrides(raw_value: str) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for line in str(raw_value or "").splitlines():
        value = line.strip()
        if not value or "=" not in value:
            continue
        key, item = value.split("=", 1)
        env_map[key.strip()] = item.strip()
    return env_map
