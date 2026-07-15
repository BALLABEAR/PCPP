from __future__ import annotations

from fastapi import APIRouter

from app.training.schemas import TrainingStatusResponse
from app.training.service import get_placeholder_status

router = APIRouter(prefix="/training", tags=["training"])


# Возвращает текущий статус реализации training-контекста
@router.get("/status", response_model=TrainingStatusResponse)
def training_status() -> TrainingStatusResponse:
    return get_placeholder_status()
