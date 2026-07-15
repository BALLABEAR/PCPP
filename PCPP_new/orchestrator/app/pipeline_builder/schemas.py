from __future__ import annotations

from pydantic import BaseModel


# DTO статуса готовности API pipeline_builder
class PipelineBuilderStatusResponse(BaseModel):
    status: str
    message: str
