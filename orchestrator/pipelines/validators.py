import re
from pathlib import Path
from typing import Any

import yaml

from orchestrator.models.model_card import ModelCard


def _to_formats(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _load_card_payload(card: ModelCard) -> dict[str, Any]:
    path = Path(card.source_path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _guess_worker_class(worker_py_path: Path) -> str:
    if not worker_py_path.exists():
        return "GeneratedWorker"
    content = worker_py_path.read_text(encoding="utf-8", errors="ignore")
    for match in re.finditer(r"class\s+([A-Za-z_]\w*)\s*(?:\(|:)", content):
        name = match.group(1)
        if name.lower() != "baseworker":
            return name
    return "GeneratedWorker"


def _resolve_worker_location(card: ModelCard) -> tuple[str, str, Path]:
    source_path = Path(card.source_path)
    model_dir = source_path.parent
    worker_py = model_dir / "worker.py"
    workers_idx = None
    parts = list(source_path.parts)
    for idx, part in enumerate(parts):
        if part == "workers":
            workers_idx = idx
            break
    if workers_idx is not None and len(parts) >= workers_idx + 4:
        task_type = parts[workers_idx + 1]
        model_dir_name = parts[workers_idx + 2]
        worker_module = f"workers.{task_type}.{model_dir_name}.worker"
        dockerfile_path = str((model_dir / "Dockerfile").resolve())
        return worker_module, dockerfile_path, worker_py
    model_id = card.id
    task_type = card.task_type
    worker_module = f"workers.{task_type}.{model_id}.worker"
    dockerfile_path = str((Path("workers") / task_type / model_id / "Dockerfile").resolve())
    return worker_module, dockerfile_path, worker_py


def build_step_from_model(card: ModelCard) -> dict[str, Any]:
    card_payload = _load_card_payload(card)
    input_formats = _to_formats(card_payload.get("accepted_input_formats")) or _to_formats(card_payload.get("input_format"))
    output_formats = _to_formats(card_payload.get("produced_output_formats")) or _to_formats(card_payload.get("output_format"))

    source_path = Path(card.source_path)
    model_dir = source_path.parent
    worker_module, dockerfile_path, worker_py = _resolve_worker_location(card)
    model_id = card.id
    task_type = card.task_type
    worker_class = _guess_worker_class(worker_py)
    image_tag = f"pcpp-{task_type}-{model_id}:gpu"
    gpu_required = bool(card_payload.get("gpu_required", True))
    execution_mode = "docker"
    return {
        "name": f"{task_type}_{model_id}",
        "model_id": model_id,
        "task_type": task_type,
        "input_formats": input_formats,
        "output_formats": output_formats,
        "worker_module": worker_module,
        "worker_class": worker_class,
        "execution_mode": execution_mode,
        "dockerfile_path": dockerfile_path,
        "image_tag": image_tag,
        "use_gpu": gpu_required,
        "cli_args": {},
    }


def validate_step_chain(steps: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not steps:
        return ["Pipeline must contain at least one step."]
    for idx in range(len(steps) - 1):
        left = steps[idx]
        right = steps[idx + 1]
        left_out = set(left.get("output_formats") or [])
        right_in = set(right.get("input_formats") or [])
        if left_out and right_in and left_out.isdisjoint(right_in):
            errors.append(
                f"Step {idx + 1} ({left['model_id']}) output formats {sorted(left_out)} "
                f"are incompatible with step {idx + 2} ({right['model_id']}) input formats {sorted(right_in)}."
            )
    return errors
