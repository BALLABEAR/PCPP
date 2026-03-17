from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from orchestrator.api.dependencies import get_db
from orchestrator.models.model_card import ModelCard

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/models")
def list_models(db: Session = Depends(get_db)) -> list[dict[str, str | None]]:
    cards = db.query(ModelCard).order_by(ModelCard.task_type, ModelCard.name).all()
    return [
        {
            "id": card.id,
            "name": card.name,
            "task_type": card.task_type,
            "description": card.description,
            "source_path": card.source_path,
        }
        for card in cards
    ]

