from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.model_onboarding.schemas import ModelPayload, RunResponse, ValidateResponse
from app.model_onboarding.service import get_run_response, run_scaffold_pipeline, validate_model_payload

router = APIRouter(prefix="/onboarding/models", tags=["onboarding"])


# Проверяет корректность данных модели перед scaffold
@router.post("/validate", response_model=ValidateResponse)
def validate_model(payload: ModelPayload) -> ValidateResponse:
    valid, errors, warnings = validate_model_payload(payload)
    return ValidateResponse(valid=valid, errors=errors, warnings=warnings)


# Запускает validate+scaffold пайплайн
@router.post("/scaffold", response_model=RunResponse)
def scaffold_model(payload: ModelPayload, db: Session = Depends(get_db)) -> RunResponse:
    run = run_scaffold_pipeline(db, payload)
    if run.run_id == "" and run.error_message:
        raise HTTPException(status_code=409, detail=run.error_message)
    return run


# Возвращает статус и логи onboarding/build запуска
@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunResponse:
    run = get_run_response(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
