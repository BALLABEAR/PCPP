from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CONTAINER_WORKSPACE_ROOT = Path("/app")


def workspace_root() -> Path:
    return Path(os.getenv("WORKSPACE_ROOT", "/app")).resolve()


def training_presets_root() -> Path:
    return workspace_root() / "training_presets"


def datasets_root() -> Path:
    return workspace_root() / "data" / "datasets"


def training_runs_root() -> Path:
    return workspace_root() / "training_runs"


def resolve_workspace_path(raw: str, *, base_dir: Path | None = None) -> Path:
    normalized = (raw or "").strip().replace("\\", "/")
    if not normalized:
        raise ValueError("Path value is empty.")
    raw_path = Path(normalized)
    if raw_path.is_absolute():
        return raw_path.resolve()

    candidates: list[Path] = []
    if base_dir is not None:
        candidates.append((base_dir / raw_path).resolve())
    candidates.append((workspace_root() / raw_path).resolve())

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def ensure_within(path: Path, parent: Path, *, label: str) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if resolved_path != resolved_parent and resolved_parent not in resolved_path.parents:
        raise ValueError(f"{label} must stay inside {resolved_parent}")


def to_container_path(path: Path) -> str:
    resolved = path.resolve()
    root = workspace_root()
    ensure_within(resolved, root, label="Path")
    return str(CONTAINER_WORKSPACE_ROOT / resolved.relative_to(root))


def to_workspace_relative(path: Path) -> str:
    resolved = path.resolve()
    root = workspace_root()
    ensure_within(resolved, root, label="Path")
    rel = resolved.relative_to(root).as_posix()
    return f"./{rel}"


@dataclass(frozen=True)
class TrainingPreset:
    profile_id: str
    name: str
    model_id: str
    task_type: str
    image_tag: str
    adapter_id: str
    repo_path: Path
    working_dir: Path
    default_train_script: Path
    default_train_config: Path
    default_finetune_checkpoint: Path | None
    dataset_kind: str
    category_file_path: Path
    partial_points_path_template: str
    complete_points_path_template: str
    modes: dict[str, dict[str, Any]]
    config_mutations: dict[str, Any]
    checkpoint_priority: list[str]
    metrics_catalog: list[dict[str, Any]]
    recommended_curves: dict[str, str]
    early_stopping_defaults: dict[str, Any]
    source_path: Path

    @classmethod
    def from_payload(cls, source_path: Path, payload: dict[str, Any]) -> "TrainingPreset":
        root = workspace_root()
        adapter_id = str(payload.get("adapter_id") or "").strip()
        if not adapter_id:
            raise ValueError(f"Training preset '{source_path.name}' must define adapter_id.")
        repo_path = resolve_workspace_path(str(payload["repo_path"]))
        working_dir = resolve_workspace_path(str(payload["working_dir"]))
        default_train_script = resolve_workspace_path(str(payload["default_train_script"]), base_dir=working_dir)
        default_train_config = resolve_workspace_path(str(payload["default_train_config"]), base_dir=working_dir)
        category_file_path = resolve_workspace_path(str(payload["dataset"]["category_file_path"]))
        default_checkpoint_raw = str(payload.get("default_finetune_checkpoint") or "").strip()
        default_checkpoint = (
            resolve_workspace_path(default_checkpoint_raw) if default_checkpoint_raw else None
        )

        for checked in (
            repo_path,
            working_dir,
            default_train_script,
            default_train_config,
            category_file_path,
        ):
            ensure_within(checked, root, label="Preset path")
        if default_checkpoint is not None:
            ensure_within(default_checkpoint, root, label="Preset checkpoint")

        return cls(
            profile_id=str(payload["profile_id"]).strip(),
            name=str(payload["name"]).strip(),
            model_id=str(payload["model_id"]).strip(),
            task_type=str(payload["task_type"]).strip(),
            image_tag=str(payload["image_tag"]).strip(),
            adapter_id=adapter_id,
            repo_path=repo_path,
            working_dir=working_dir,
            default_train_script=default_train_script,
            default_train_config=default_train_config,
            default_finetune_checkpoint=default_checkpoint,
            dataset_kind=str(payload["dataset"]["kind"]).strip(),
            category_file_path=category_file_path,
            partial_points_path_template=str(payload["dataset"]["partial_points_path"]).strip(),
            complete_points_path_template=str(payload["dataset"]["complete_points_path"]).strip(),
            modes=dict(payload.get("modes") or {}),
            config_mutations=dict(payload.get("config_mutations") or {}),
            checkpoint_priority=[str(item).strip() for item in payload.get("checkpoint_rules", {}).get("priority", []) if str(item).strip()],
            metrics_catalog=[
                dict(item)
                for item in (payload.get("metrics_catalog") or [])
                if isinstance(item, dict)
            ],
            recommended_curves=dict(payload.get("recommended_curves") or {}),
            early_stopping_defaults=dict(payload.get("early_stopping_defaults") or {}),
            source_path=source_path,
        )


def load_training_preset(profile_id: str) -> TrainingPreset:
    root = training_presets_root()
    for candidate in list(root.glob("*.yaml")) + list(root.glob("*.yml")):
        payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if str(payload.get("profile_id", "")).strip() == profile_id:
            return TrainingPreset.from_payload(candidate, payload)
    raise FileNotFoundError(f"Training preset not found: {profile_id}")


def list_training_presets() -> list[TrainingPreset]:
    presets: list[TrainingPreset] = []
    root = training_presets_root()
    for candidate in sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml"))):
        payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        presets.append(TrainingPreset.from_payload(candidate, payload))
    return presets
