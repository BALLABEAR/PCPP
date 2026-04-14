import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from orchestrator.onboarding import dependency_scan as dep_scan
from orchestrator.onboarding import docker_ops
from orchestrator.onboarding import filesystem_ops as fs_ops
from orchestrator.onboarding import preflight_ops
from orchestrator.onboarding import runtime_ops
from orchestrator.onboarding.error_classifier import classify_error
from orchestrator.onboarding.run_state import RUNS as _RUNS
from orchestrator.onboarding.run_state import RUNS_LOCK as _RUNS_LOCK
from orchestrator.onboarding.run_state import utc_now as _utc_now
from orchestrator.onboarding.schemas import (
    ActionRunRequest,
    BuildRequest,
    CleanupBackupsRequest,
    CleanupRequest,
    PreflightScanRequest,
    RegistryCheckRequest,
    RunStatusResponse,
    ScaffoldModelRequest,
    SmokeRunRequest,
    ValidateModelRequest,
    ValidateModelResponse,
)
from orchestrator.models import SessionLocal
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.registry.scanner import scan_model_cards

router = APIRouter(prefix="/onboarding/models", tags=["onboarding"])


def _workspace_root() -> Path:
    return Path(os.getenv("WORKSPACE_ROOT", "/app")).resolve()


def _resolve_user_path(raw: str) -> Path:
    normalized = (raw or "").strip().replace("\\", "/")
    path = Path(normalized)
    if not path.is_absolute():
        path = _workspace_root() / path
    return path.resolve()


def _start_run(kind: Literal["build", "smoke", "command"], command: list[str], cwd: Path) -> str:
    run_id = uuid.uuid4().hex
    record = {
        "run_id": run_id,
        "kind": kind,
        "status": "pending",
        "command": command,
        "cwd": str(cwd),
        "logs": "",
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "exit_code": None,
        "error_hint": None,
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = record

    def _runner() -> None:
        with _RUNS_LOCK:
            _RUNS[run_id]["status"] = "running"
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                with _RUNS_LOCK:
                    _RUNS[run_id]["logs"] += line
            process.wait()
            exit_code = int(process.returncode or 0)
            with _RUNS_LOCK:
                _RUNS[run_id]["exit_code"] = exit_code
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "completed" if exit_code == 0 else "failed"
                if exit_code != 0:
                    _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])
        except Exception as exc:
            with _RUNS_LOCK:
                _RUNS[run_id]["logs"] += f"\n[runner-error] {exc}\n"
                _RUNS[run_id]["exit_code"] = 1
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "failed"
                _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])

    threading.Thread(target=_runner, daemon=True).start()
    return run_id


@router.post("/validate", response_model=ValidateModelResponse)
def validate_model(payload: ValidateModelRequest) -> ValidateModelResponse:
    return preflight_ops.validate_request(payload, resolve_user_path=_resolve_user_path)


@router.post("/preflight-scan")
def preflight_scan(payload: PreflightScanRequest) -> dict[str, Any]:
    return preflight_ops.scan_preflight(payload, resolve_user_path=_resolve_user_path)


@router.post("/scaffold")
def scaffold_model(payload: ScaffoldModelRequest) -> dict[str, Any]:
    validation = preflight_ops.validate_request(payload, resolve_user_path=_resolve_user_path)
    if not validation.valid:
        raise HTTPException(status_code=422, detail={"errors": validation.errors, "warnings": validation.warnings})

    root = _workspace_root()
    repo = _resolve_user_path(payload.repo_path)
    target_dir = root / "workers" / payload.task_type / payload.model_id
    if target_dir.exists() and not payload.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Target folder already exists: {target_dir}. Set overwrite=true to replace with backup.",
        )
    if target_dir.exists() and payload.overwrite:
        fs_ops.backup_if_exists(target_dir)

    cmd = [
        "python",
        "workers/base/create_model_adapter.py",
        "--task-type",
        payload.task_type,
        "--model-id",
        payload.model_id,
        "--repo-path",
        payload.repo_path,
        "--entry-command",
        preflight_ops.guess_entry_command(payload, resolve_user_path=_resolve_user_path),
        "--weights-path",
        payload.weights_path,
        "--config-path",
        payload.config_path,
        "--input-format",
        ",".join(validation.normalized["input_formats"]),
        "--output-format",
        ",".join(validation.normalized["output_formats"]),
        "--description",
        payload.description,
    ]
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    if result.returncode != 0:
        logs = (result.stdout or "") + "\n" + (result.stderr or "")
        raise HTTPException(status_code=500, detail={"message": "Scaffold generation failed", "logs": logs})

    manifest_path = target_dir / "runtime.manifest.yaml"
    resolved_pips, resolved_reqs, resolved_system = dep_scan.normalize_dependency_inputs(
        repo_path=payload.repo_path,
        extra_pip_packages=payload.extra_pip_packages,
        pip_requirements_files=payload.pip_requirements_files,
        system_packages=payload.system_packages,
        resolve_user_path=_resolve_user_path,
    )
    detected_build_steps = dep_scan.collect_build_step_hints(repo)
    effective_build_steps = payload.extra_build_steps if payload.extra_build_steps else detected_build_steps
    effective_base_image = payload.base_image.strip()
    if detected_build_steps:
        for pkg in ("ninja-build", "cmake"):
            if pkg not in resolved_system:
                resolved_system.append(pkg)
    runtime_ops.patch_runtime_manifest(
        manifest_path,
        extra_pip_packages=resolved_pips,
        pip_requirements_files=resolved_reqs,
        pip_extra_args=payload.pip_extra_args,
        system_packages=resolved_system,
        base_image=effective_base_image,
        extra_build_steps=effective_build_steps,
        env_overrides=payload.env_overrides,
    )
    runtime_ops.patch_dockerfile_base_image(target_dir / "Dockerfile", effective_base_image)
    db = SessionLocal()
    try:
        scan_model_cards(db, root)
    finally:
        db.close()
    runtime_ops.update_model_runtime_status(
        model_id=payload.model_id,
        build_ok=False,
        smoke_ok=False,
        manifest_hash=runtime_ops.manifest_hash(root, payload.task_type, payload.model_id),
        last_error=None,
        mark_verified=False,
    )

    return {
        "status": "ok",
        "target_dir": str(target_dir),
        "stdout": result.stdout,
        "warnings": validation.warnings,
        "autodetected_build_steps": effective_build_steps,
        "autodetected_base_image": effective_base_image,
    }


@router.post("/build")
def build_model(payload: BuildRequest) -> dict[str, str]:
    root = _workspace_root()
    source_dockerfile = root / "workers" / payload.task_type / payload.model_id / "Dockerfile"
    if not source_dockerfile.exists():
        raise HTTPException(status_code=404, detail=f"Dockerfile not found: {source_dockerfile}")
    stage_dir, dockerfile = fs_ops.prepare_build_context(
        root=root,
        task_type=payload.task_type,
        model_id=payload.model_id,
        resolve_user_path=_resolve_user_path,
    )
    if not dockerfile.exists():
        raise HTTPException(status_code=404, detail=f"Dockerfile not found in stage: {dockerfile}")
    image_tag = payload.image_tag or f"pcpp-{payload.task_type}-{payload.model_id}:gpu"
    run_id = docker_ops.start_docker_build_run(
        tag=image_tag,
        dockerfile=dockerfile,
        root=stage_dir,
        model_id=payload.model_id,
        task_type=payload.task_type,
        no_cache=payload.no_cache,
        cleanup_path=stage_dir,
        runs=_RUNS,
        runs_lock=_RUNS_LOCK,
        utc_now=_utc_now,
        classify_error=classify_error,
        update_model_runtime_status=runtime_ops.update_model_runtime_status,
        manifest_hash=lambda tt, mid: runtime_ops.manifest_hash(_workspace_root(), tt, mid),
    )
    return {"run_id": run_id, "status": "running"}


@router.post("/smoke-run")
def smoke_run(payload: SmokeRunRequest) -> dict[str, str]:
    image_tag = payload.image_tag or f"pcpp-{payload.task_type}-{payload.model_id}:gpu"
    module_name = f"workers.{payload.task_type}.{payload.model_id}.worker"
    db = SessionLocal()
    try:
        card = db.get(ModelCard, payload.model_id)
        if card:
            source = Path(card.source_path)
            parts = list(source.parts)
            if "workers" in parts:
                i = parts.index("workers")
                if len(parts) >= i + 4:
                    module_name = f"workers.{parts[i + 1]}.{parts[i + 2]}.worker"
    finally:
        db.close()
    run_id = docker_ops.start_docker_smoke_run(
        image_tag=image_tag,
        module_name=module_name,
        input_data_kind=payload.input_data_kind,
        use_gpu=payload.use_gpu,
        model_args=(payload.model_args or []) + preflight_ops.clean_cli_tokens(payload.smoke_args),
        model_id=payload.model_id,
        runs=_RUNS,
        runs_lock=_RUNS_LOCK,
        utc_now=_utc_now,
        classify_error=classify_error,
        update_model_runtime_status=runtime_ops.update_model_runtime_status,
    )
    return {"run_id": run_id, "status": "running"}


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunStatusResponse(**run)


@router.post("/command")
def run_command(payload: ActionRunRequest) -> dict[str, str]:
    root = _workspace_root()
    cwd = _resolve_user_path(payload.cwd) if payload.cwd else root
    run_id = _start_run("command", payload.command, cwd)
    return {"run_id": run_id, "status": "running"}


@router.post("/cleanup")
def cleanup_scaffold(payload: CleanupRequest) -> dict[str, str]:
    root = _workspace_root()
    target_dir = (root / "workers" / payload.task_type / payload.model_id).resolve()
    workers_root = (root / "workers").resolve()
    if workers_root not in target_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid cleanup target.")
    if target_dir.exists():
        shutil.rmtree(target_dir)
        return {"status": "deleted", "target_dir": str(target_dir)}
    return {"status": "not_found", "target_dir": str(target_dir)}


@router.post("/cleanup-backups")
def cleanup_backups(payload: CleanupBackupsRequest) -> dict[str, Any]:
    root = _workspace_root()
    now = datetime.now(timezone.utc)
    matched = fs_ops.collect_backup_dirs(root, task_type=payload.task_type, model_id=payload.model_id)
    selected: list[Path] = []
    for item in matched:
        if payload.older_than_hours <= 0:
            selected.append(item)
            continue
        mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        age_hours = (now - mtime).total_seconds() / 3600.0
        if age_hours >= payload.older_than_hours:
            selected.append(item)

    deleted: list[str] = []
    if payload.apply:
        for item in selected:
            shutil.rmtree(item, ignore_errors=True)
            deleted.append(str(item))
    result = {
        "status": "ok",
        "dry_run": not payload.apply,
        "matched_count": len(matched),
        "selected_count": len(selected),
        "paths": [str(p) for p in selected] if not payload.apply else deleted,
    }
    return result


@router.post("/registry-check")
def registry_check(payload: RegistryCheckRequest) -> dict[str, Any]:
    db = SessionLocal()
    try:
        card = db.query(ModelCard).filter(ModelCard.id == payload.model_id).first()
        status = db.get(ModelRuntimeStatus, payload.model_id)
    finally:
        db.close()
    ready = bool(status and status.build_ok and status.smoke_ok)
    reason = None
    if card is None:
        reason = "model_not_registered"
    elif status is None:
        reason = "model_not_verified"
    elif not status.build_ok:
        reason = "build_not_successful"
    elif not status.smoke_ok:
        reason = "smoke_not_successful"
    return {
        "registered": card is not None,
        "ready": ready,
        "reason": reason,
        "model_id": payload.model_id,
    }


@router.post("/registry-reconcile")
def registry_reconcile() -> dict[str, Any]:
    root = _workspace_root()
    db = SessionLocal()
    try:
        found = scan_model_cards(db, root)
    finally:
        db.close()
    return {"status": "ok", "found": found}
