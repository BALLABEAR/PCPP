import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.api.dependencies import get_db
from orchestrator.flow_validation import list_flow_worker_modules, validate_flow_formats
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.onboarding.runtime_ops import evaluate_runtime_readiness, manifest_hash_for_model_card
from orchestrator.models import SessionLocal
from orchestrator.models.task import Task
from orchestrator.prefect_client import PrefectClient, get_task_logs
from flows.flow_definitions import get_flow_definition

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger("orchestrator.tasks")
prefect_client = PrefectClient(SessionLocal)


def _validate_flow_runtime_readiness(db: Session, flow_id: str, flow_params: dict[str, Any] | None) -> None:
    worker_modules = list_flow_worker_modules(flow_id=flow_id, flow_params=flow_params)
    if not worker_modules:
        return
    for worker_module in worker_modules:
        parts = worker_module.split(".")
        if len(parts) < 4 or parts[0] != "workers":
            continue
        model_id = parts[2]
        card = db.get(ModelCard, model_id)
        if card is None:
            continue
        status = db.get(ModelRuntimeStatus, model_id)
        ready, reason = evaluate_runtime_readiness(
            status,
            current_manifest_hash=manifest_hash_for_model_card(card.source_path),
        )
        if not ready:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pipeline step model '{model_id}' is not runtime-ready "
                    f"({reason or 'unknown_reason'}). Rebuild/smoke-check it before running the pipeline."
                ),
            )


class CreateTaskRequest(BaseModel):
    input_bucket: str
    input_key: str
    input_keys: list[str] | None = None
    flow_id: str = "pipeline_flow"
    flow_params: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    id: str
    status: str
    input_bucket: str
    input_key: str
    result_bucket: str | None
    result_key: str | None
    flow_run_name: str | None
    error_message: str | None
    created_at: Any | None = None
    updated_at: Any | None = None


@router.post("", response_model=TaskResponse)
def create_task(payload: CreateTaskRequest, db: Session = Depends(get_db)) -> TaskResponse:
    if payload.input_keys is not None and len(payload.input_keys) == 0:
        raise HTTPException(status_code=422, detail="input_keys cannot be empty")
    if not get_flow_definition(payload.flow_id):
        raise HTTPException(status_code=422, detail=f"Unknown flow_id: {payload.flow_id}")

    try:
        validate_flow_formats(
            flow_id=payload.flow_id,
            flow_params=payload.flow_params,
            input_key=payload.input_key,
            input_keys=payload.input_keys,
        )
        _validate_flow_runtime_readiness(db, payload.flow_id, payload.flow_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    task = Task(
        status="pending",
        input_bucket=payload.input_bucket,
        input_key=payload.input_key,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    flow_params = dict(payload.flow_params or {})
    if payload.input_keys:
        flow_params["input_keys"] = payload.input_keys
    if task.created_at:
        flow_params["task_created_at_utc"] = task.created_at.isoformat()

    flow_run_name = prefect_client.trigger_flow(
        task_id=task.id,
        input_bucket=task.input_bucket,
        input_key=task.input_key,
        flow_id=payload.flow_id,
        flow_params=flow_params,
    )
    task.flow_run_name = flow_run_name
    db.commit()
    db.refresh(task)

    logger.info("Task created id=%s flow_run=%s", task.id, flow_run_name)
    return TaskResponse.model_validate(task, from_attributes=True)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskResponse:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse.model_validate(task, from_attributes=True)


@router.get("/{task_id}/logs")
def get_task_runtime_logs(task_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "logs": get_task_logs(task_id)}


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(task_id: str, db: Session = Depends(get_db)) -> TaskResponse:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail=f"Task is already in terminal state: {task.status}")
    prefect_client.cancel_task(task_id)
    db.refresh(task)
    return TaskResponse.model_validate(task, from_attributes=True)
