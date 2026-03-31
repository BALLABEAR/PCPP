from fastapi import APIRouter, Depends
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Any
import yaml

from orchestrator.api.dependencies import get_db
from orchestrator.models.model_card import ModelCard

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/models")
def list_models(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    cards = db.query(ModelCard).order_by(ModelCard.task_type, ModelCard.name).all()
    result: list[dict] = []
    for card in cards:
        meta: dict = {}
        try:
            payload = yaml.safe_load(Path(card.source_path).read_text(encoding="utf-8")) or {}
            meta = {
                "input_format": payload.get("input_format"),
                "output_format": payload.get("output_format"),
                "accepted_input_formats": payload.get("accepted_input_formats"),
                "produced_output_formats": payload.get("produced_output_formats"),
                "preferred_output_format": payload.get("preferred_output_format"),
                "gpu_required": payload.get("gpu_required"),
                "gpu_memory_mb": payload.get("gpu_memory_mb"),
                "speed": payload.get("speed"),
                "quality": payload.get("quality"),
                "params": payload.get("params"),
            }
        except Exception:
            meta = {}
        result.append(
            {
                "id": card.id,
                "name": card.name,
                "task_type": card.task_type,
                "description": card.description,
                "source_path": card.source_path,
                **meta,
            }
        )
    return result

