from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# DTO карточки модели для выдачи в API каталога
class ModelResponse(BaseModel):
    model_id: str
    task_type: str
    repo_path: str
    weights_path: str
    config_path: str
    smoke_input_path: str
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None
