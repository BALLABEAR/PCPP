import os
import shutil
from pathlib import Path
from typing import Any

import docker
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import yaml

from orchestrator.api.dependencies import get_db
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.registry.scanner import scan_model_cards

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
        readiness = db.get(ModelRuntimeStatus, card.id)
        ready = bool(readiness and readiness.build_ok and readiness.smoke_ok)
        readiness_reason = None
        if readiness is None:
            readiness_reason = "model_not_verified"
        elif not readiness.build_ok:
            readiness_reason = "build_not_successful"
        elif not readiness.smoke_ok:
            readiness_reason = "smoke_not_successful"
        result.append(
            {
                "id": card.id,
                "name": card.name,
                "task_type": card.task_type,
                "description": card.description,
                "source_path": card.source_path,
                "ready": ready,
                "readiness_reason": readiness_reason,
                "last_verified_at": readiness.last_verified_at.isoformat() if readiness and readiness.last_verified_at else None,
                **meta,
            }
        )
    return result


@router.delete("/models/{model_id}")
def delete_model(model_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    card = db.get(ModelCard, model_id)
    if not card:
        raise HTTPException(status_code=404, detail="Model not found")

    root = Path(os.getenv("WORKSPACE_ROOT", "/app")).resolve()
    workers_root = (root / "workers").resolve()
    source_path = Path(card.source_path).resolve()
    target_dir = source_path.parent
    if workers_root not in target_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid model path")

    removed_worker_dir = False
    if target_dir.exists():
        shutil.rmtree(target_dir)
        removed_worker_dir = True

    found_after_scan = scan_model_cards(db, root)

    docker_removed: list[str] = []
    docker_errors: list[str] = []
    prune_result: dict[str, Any] = {}
    image_prefix = f"pcpp-{card.task_type}-{card.id}"
    try:
        client = docker.from_env()
        for image in client.images.list():
            for tag in image.tags:
                if tag.startswith(f"{image_prefix}:"):
                    try:
                        client.images.remove(tag, force=True)
                        docker_removed.append(tag)
                    except Exception as exc:
                        docker_errors.append(f"{tag}: {exc}")
        try:
            prune_result = client.images.prune(filters={"dangling": True}) or {}
        except Exception as exc:
            docker_errors.append(f"prune: {exc}")
    except Exception as exc:
        docker_errors.append(f"docker client: {exc}")

    return {
        "status": "deleted",
        "model_id": model_id,
        "task_type": card.task_type,
        "removed_worker_dir": removed_worker_dir,
        "worker_dir": str(target_dir),
        "docker_removed_tags": docker_removed,
        "docker_errors": docker_errors,
        "docker_prune": prune_result,
        "registry_found_after_scan": found_after_scan,
    }

