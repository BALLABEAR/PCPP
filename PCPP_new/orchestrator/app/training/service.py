from __future__ import annotations

from app.training.schemas import TrainingStatusResponse


# Возвращает признак, что training API пока не реализован
def get_placeholder_status() -> TrainingStatusResponse:
    return TrainingStatusResponse(status="not_implemented", message="Training API will be added in next iteration.")
