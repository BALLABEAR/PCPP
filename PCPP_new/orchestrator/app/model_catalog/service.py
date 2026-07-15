from __future__ import annotations

from sqlalchemy.orm import Session

from app.model_onboarding.repository import list_active_models
from app.model_catalog.schemas import ModelResponse


# Возвращает список активных моделей в формате API-схем
def list_models(db: Session) -> list[ModelResponse]:
    rows = list_active_models(db)
    return [
        ModelResponse(
            model_id=row.model_id,
            task_type=row.task_type,
            repo_path=row.repo_path,
            weights_path=row.weights_path,
            config_path=row.config_path,
            smoke_input_path=row.smoke_input_path,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
