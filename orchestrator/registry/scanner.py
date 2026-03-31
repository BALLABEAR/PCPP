from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from orchestrator.models.model_card import ModelCard


def scan_model_cards(db: Session, workspace_root: Path) -> int:
    found = 0
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    workers_root = workspace_root / "workers"
    if not workers_root.exists():
        db.commit()
        return 0
    for card_path in workers_root.rglob("model_card.yaml"):
        # Skip backup folders created by onboarding overwrite mode.
        if any(".bak_" in part for part in card_path.parts):
            continue
        with card_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        card_id = payload.get("id")
        if not card_id:
            continue
        if card_id in seen_ids:
            continue
        seen_ids.add(card_id)
        seen_paths.add(str(card_path))

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

    # Reconcile stale registry rows: remove records pointing to missing or backup paths.
    for row in db.query(ModelCard).all():
        source = Path(row.source_path)
        if ".bak_" in row.source_path or (row.id not in seen_ids) or (row.source_path not in seen_paths) or (not source.exists()):
            db.delete(row)
    db.commit()
    return found
