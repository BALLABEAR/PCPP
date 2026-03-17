from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from orchestrator.models.model_card import ModelCard


def scan_model_cards(db: Session, workspace_root: Path) -> int:
    found = 0
    for card_path in workspace_root.rglob("model_card.yaml"):
        with card_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        card_id = payload.get("id")
        if not card_id:
            continue

        existing = db.get(ModelCard, card_id)
        if existing:
            existing.name = payload.get("name", card_id)
            existing.task_type = payload.get("task_type", "unknown")
            existing.description = payload.get("description", "")
            existing.source_path = str(card_path)
        else:
            db.add(
                ModelCard(
                    id=card_id,
                    name=payload.get("name", card_id),
                    task_type=payload.get("task_type", "unknown"),
                    description=payload.get("description", ""),
                    source_path=str(card_path),
                )
            )
        found += 1
    db.commit()
    return found
