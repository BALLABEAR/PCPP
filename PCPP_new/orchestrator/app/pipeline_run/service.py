from __future__ import annotations

from app.pipeline_run.schemas import PipelineRunStatusResponse


# Возвращает признак, что контекст pipeline_run пока не реализован
def get_placeholder_status() -> PipelineRunStatusResponse:
    return PipelineRunStatusResponse(status="not_implemented", message="Pipeline run API will be added in next iteration.")
