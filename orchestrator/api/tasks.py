import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orchestrator.api.dependencies import get_db
from orchestrator.models import SessionLocal
from orchestrator.models.task import Task
from orchestrator.prefect_client import PrefectClient

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger("orchestrator.tasks")
prefect_client = PrefectClient(SessionLocal)


class CreateTaskRequest(BaseModel):
    input_bucket: str
    input_key: str
    flow_id: Literal[
        "stage2_test_flow",
        "stage4_segmentation_completion_flow",
        "stage4_real_two_model_flow",
        "stage4_snowflake_only_flow",
        "stage4_shape_as_points_only_flow",
    ] = (
        "stage2_test_flow"
    )
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


@router.post("", response_model=TaskResponse)
def create_task(payload: CreateTaskRequest, db: Session = Depends(get_db)) -> TaskResponse:
    task = Task(
        status="pending",
        input_bucket=payload.input_bucket,
        input_key=payload.input_key,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    flow_run_name = prefect_client.trigger_flow(
        task_id=task.id,
        input_bucket=task.input_bucket,
        input_key=task.input_key,
        flow_id=payload.flow_id,
        flow_params=payload.flow_params,
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

