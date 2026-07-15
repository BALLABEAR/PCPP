from __future__ import annotations

from pydantic import BaseModel


# DTO статуса готовности API обучения
class TrainingStatusResponse(BaseModel):
    status: str
    message: str
