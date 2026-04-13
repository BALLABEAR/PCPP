import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.api.dependencies import get_db
from orchestrator.flow_validation import validate_flow_formats
from orchestrator.models import SessionLocal
from orchestrator.models.task import Task
from orchestrator.prefect_client import PrefectClient, get_task_logs
from flows.flow_definitions import get_flow_definition

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger("orchestrator.tasks")
prefect_client = PrefectClient(SessionLocal)


def _debug_log(hypothesis_id: str, message: str, data: dict[str, Any] | None = None, run_id: str = "task-run") -> None:
    # #region agent log
    payload = {
        "sessionId": "e69ff4",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": "orchestrator/api/tasks.py",
        "message": message,
        "data": data or {},
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    try:
        with Path("debug-e69ff4.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # #endregion


class CreateTaskRequest(BaseModel):
    input_bucket: str
    input_key: str
    input_keys: list[str] | None = None
    flow_id: str = "stage2_test_flow"
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
    # #region agent log
    _debug_log(
        "H1",
        "create_task received",
        {
            "flow_id": payload.flow_id,
            "input_key": payload.input_key,
            "flow_params_keys": sorted(list((payload.flow_params or {}).keys())),
            "pipeline_steps_len": len((payload.flow_params or {}).get("pipeline_steps", []) or []),
        },
    )
    # #endregion
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
    except ValueError as exc:
        # #region agent log
        _debug_log("H2", "validate_flow_formats failed", {"error": str(exc)})
        # #endregion
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
    # #region agent log
    _debug_log(
        "H3",
        "task created and triggered",
        {"task_id": task.id, "flow_run_name": flow_run_name, "flow_id": payload.flow_id},
        run_id=task.id,
    )
    # #endregion
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

