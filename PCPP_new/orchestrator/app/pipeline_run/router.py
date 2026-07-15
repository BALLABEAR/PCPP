from __future__ import annotations

from fastapi import APIRouter

from app.pipeline_run.schemas import PipelineRunStatusResponse
from app.pipeline_run.service import get_placeholder_status

router = APIRouter(prefix="/pipeline/run", tags=["pipeline-run"])


# Возвращает текущий статус реализации контекста pipeline_run
@router.get("/status", response_model=PipelineRunStatusResponse)
def pipeline_run_status() -> PipelineRunStatusResponse:
    return get_placeholder_status()
