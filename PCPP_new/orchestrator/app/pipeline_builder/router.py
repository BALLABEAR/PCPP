from __future__ import annotations

from fastapi import APIRouter

from app.pipeline_builder.schemas import PipelineBuilderStatusResponse
from app.pipeline_builder.service import get_placeholder_status

router = APIRouter(prefix="/pipeline/builder", tags=["pipeline-builder"])


# Возвращает текущий статус реализации pipeline_builder
@router.get("/status", response_model=PipelineBuilderStatusResponse)
def pipeline_builder_status() -> PipelineBuilderStatusResponse:
    return get_placeholder_status()
