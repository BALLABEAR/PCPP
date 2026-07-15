from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.model_catalog.schemas import ModelResponse
from app.model_catalog.service import list_models

router = APIRouter(prefix="/onboarding/models", tags=["model-catalog"])

# Возвращает список активных моделей из каталога
@router.get("", response_model=list[ModelResponse])
def get_models(db: Session = Depends(get_db)) -> list[ModelResponse]:
    return list_models(db)
