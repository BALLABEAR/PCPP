from __future__ import annotations

from app.pipeline_builder.schemas import PipelineBuilderStatusResponse


# Возвращает признак, что контекст pipeline_builder пока не реализован
def get_placeholder_status() -> PipelineBuilderStatusResponse:
    return PipelineBuilderStatusResponse(status="not_implemented", message="Pipeline builder API will be added in next iteration.")
