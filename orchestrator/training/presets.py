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
    repo_path: Path
    working_dir: Path
    default_train_script: Path | None
    default_train_config: Path | None
    default_finetune_checkpoint: Path | None
    command_template: list[str]
    args_template: list[str]
    env_template: dict[str, str]
    preprocess: list[dict[str, Any]]
    dataset_contract: dict[str, Any]
    dataset_export: dict[str, Any]
    config_patch_rules: list[dict[str, Any]]
    finetune_contract: dict[str, Any]
    native_extensions: list[dict[str, Any]]
    form_fields: list[dict[str, Any]]
    modes: dict[str, dict[str, Any]]
    checkpoint_priority: list[str]
    checkpoint_search_roots: list[str]
    artifacts_dir: str
    metrics_catalog: list[dict[str, Any]]
    recommended_curves: dict[str, str]
    early_stopping_defaults: dict[str, Any]
    geometry_normalization_supported: bool
    geometry_normalization_default: bool
    source_path: Path

    @classmethod
    def from_payload(cls, source_path: Path, payload: dict[str, Any]) -> "TrainingPreset":
        root = workspace_root()

        profile_id = str(payload.get("profile_id") or "").strip()
        model_id = str(payload.get("model_id") or "").strip()
        task_type = str(payload.get("task_type") or "").strip()
        name = str(payload.get("name") or profile_id or model_id).strip()
        image_tag = str(payload.get("image_tag") or "").strip()
        repo_path_raw = str(payload.get("repo_path") or "").strip()
        working_dir_raw = str(payload.get("working_dir") or "").strip()
        if not repo_path_raw:
            raise ValueError("Field 'repo_path' is required (path to model repository).")
        if not working_dir_raw:
            raise ValueError("Field 'working_dir' is required (directory where training command runs).")
        repo_path = resolve_workspace_path(repo_path_raw)
        working_dir = resolve_workspace_path(working_dir_raw, base_dir=repo_path)

        default_train_script_raw = str(payload.get("default_train_script") or payload.get("train_script") or "").strip()
        default_train_script = (
            resolve_workspace_path(default_train_script_raw, base_dir=working_dir)
            if default_train_script_raw
            else None
        )
        default_train_config_raw = str(payload.get("default_train_config") or payload.get("config_path") or "").strip()
        default_train_config = (
            resolve_workspace_path(default_train_config_raw, base_dir=working_dir)
            if default_train_config_raw
            else None
        )
        default_checkpoint_raw = str(payload.get("default_finetune_checkpoint") or payload.get("checkpoint_input") or "").strip()
        default_checkpoint = resolve_workspace_path(default_checkpoint_raw) if default_checkpoint_raw else None

        for checked in [repo_path, working_dir, *( [default_train_script] if default_train_script else [] ), *( [default_train_config] if default_train_config else [] )]:
            ensure_within(checked, root, label="Preset path")
        if default_checkpoint is not None:
            ensure_within(default_checkpoint, root, label="Preset checkpoint")

        command_template = [str(item).strip() for item in (payload.get("command_template") or []) if str(item).strip()]
        args_template = [str(item).strip() for item in (payload.get("args_template") or payload.get("args") or []) if str(item).strip()]
        env_template = {str(k): str(v) for k, v in dict(payload.get("env") or {}).items() if str(k).strip()}

        modes = dict(payload.get("modes") or {"scratch": {}, "finetune": {}})
        if not modes:
            modes = {"scratch": {}}

        checkpoint_rules = dict(payload.get("checkpoint_rules") or {})
        checkpoint_priority = [str(item).strip() for item in checkpoint_rules.get("priority", []) if str(item).strip()]
        checkpoint_search_roots = [str(item).strip() for item in checkpoint_rules.get("search_roots", []) if str(item).strip()]
        if not checkpoint_search_roots:
            checkpoint_search_roots = ["{run_dir}"]

        artifacts_dir = str(payload.get("artifacts_dir") or "{run_dir}/artifacts").strip()
        preprocess = [dict(item) for item in (payload.get("preprocess") or []) if isinstance(item, dict)]
        dataset_contract = dict(payload.get("dataset_contract") or {})
        dataset_export = dict(payload.get("dataset_export") or {})
        config_patch_rules = [dict(item) for item in (payload.get("config_patch_rules") or []) if isinstance(item, dict)]
        finetune_contract = dict(payload.get("finetune_contract") or {})
        native_extensions = [dict(item) for item in (payload.get("native_extensions") or []) if isinstance(item, dict)]

        form_fields = [dict(item) for item in (payload.get("form_fields") or payload.get("dataset_fields") or []) if isinstance(item, dict)]
        metrics_catalog = [dict(item) for item in (payload.get("metrics_catalog") or []) if isinstance(item, dict)]

        if not profile_id:
            raise ValueError("Field 'profile_id' is required (unique training profile id).")
        if not model_id:
            raise ValueError("Field 'model_id' is required (registered model id).")
        if not task_type:
            raise ValueError("Field 'task_type' is required (completion/upsampling/meshing/etc).")
        if not image_tag:
            raise ValueError("Field 'image_tag' is required (docker image used for training run).")

        return cls(
            profile_id=profile_id,
            name=name,
            model_id=model_id,
            task_type=task_type,
            image_tag=image_tag,
            repo_path=repo_path,
            working_dir=working_dir,
            default_train_script=default_train_script,
            default_train_config=default_train_config,
            default_finetune_checkpoint=default_checkpoint,
            command_template=command_template,
            args_template=args_template,
            env_template=env_template,
            preprocess=preprocess,
            dataset_contract=dataset_contract,
            dataset_export=dataset_export,
            config_patch_rules=config_patch_rules,
            finetune_contract=finetune_contract,
            native_extensions=native_extensions,
            form_fields=form_fields,
            modes=modes,
            checkpoint_priority=checkpoint_priority,
            checkpoint_search_roots=checkpoint_search_roots,
            artifacts_dir=artifacts_dir,
            metrics_catalog=metrics_catalog,
            recommended_curves=dict(payload.get("recommended_curves") or {}),
            early_stopping_defaults=dict(payload.get("early_stopping_defaults") or {}),
            geometry_normalization_supported=bool(payload.get("geometry_normalization_supported", True)),
            geometry_normalization_default=bool(payload.get("geometry_normalization_default", True)),
            source_path=source_path,
        )


def load_training_preset(profile_id: str) -> TrainingPreset:
    root = training_presets_root()
    for candidate in list(root.glob("*.yaml")) + list(root.glob("*.yml")):
        payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if str(payload.get("profile_id", "")).strip() == profile_id:
            return TrainingPreset.from_payload(candidate, payload)
    raise FileNotFoundError(f"Training preset not found: {profile_id}")


def find_training_preset_by_model(model_id: str) -> TrainingPreset | None:
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    for preset in list_training_presets():
        if preset.model_id == wanted:
            return preset
    return None


def list_training_presets() -> list[TrainingPreset]:
    presets: list[TrainingPreset] = []
    root = training_presets_root()
    for candidate in sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml"))):
        payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        presets.append(TrainingPreset.from_payload(candidate, payload))
    return presets


def save_training_preset(payload: dict[str, Any], *, overwrite: bool = False) -> TrainingPreset:
    root = training_presets_root()
    root.mkdir(parents=True, exist_ok=True)
    profile_id = str(payload.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("profile_id is required.")
    path = root / f"{profile_id}.yaml"
    if path.exists() and not overwrite:
        raise ValueError(f"Training preset already exists: {profile_id}")

    parsed = TrainingPreset.from_payload(path, payload)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return parsed
