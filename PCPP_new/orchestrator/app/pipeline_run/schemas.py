from __future__ import annotations

from pydantic import BaseModel


# DTO статуса готовности API pipeline_run
class PipelineRunStatusResponse(BaseModel):
    status: str
    message: str
