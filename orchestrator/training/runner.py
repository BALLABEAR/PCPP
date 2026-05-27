from __future__ import annotations

import json
import os
import shlex
import threading
import hashlib
import shutil
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from orchestrator.models import SessionLocal
from orchestrator.models.training_run import TrainingRun
from orchestrator.training.checkpoints import resolve_best_checkpoint
from orchestrator.training.logs import append_log
from orchestrator.training.metrics import (
    EarlyStoppingConfig,
    default_early_stopping_state,
    early_stopping_state_path_for_run,
    evaluate_early_stopping,
    metric_history_path_for_run,
    write_early_stopping_state,
)
from orchestrator.training.presets import (
    TrainingPreset,
    ensure_within,
    resolve_workspace_path,
    to_container_path,
    to_workspace_relative,
    training_runs_root,
    workspace_root,
)
from workers.base.point_cloud_io import load_points, save_points

_ACTIVE_RUNS_LOCK = threading.Lock()
_ACTIVE_RUNS: dict[str, dict[str, Any]] = {}
COMPLETION3D_EXPORTER_VERSION = "completion3d_h5_v6"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def discover_workspace_bind_source() -> str:
    root = workspace_root()
    host_hint = os.getenv("HOST_WORKSPACE_ROOT", "").strip()
    if host_hint:
        return host_hint

    hostname = os.getenv("HOSTNAME", "").strip()
    if not hostname:
        return str(root)

    try:
        import docker

        client = docker.from_env()
        container = client.containers.get(hostname)
        mounts = container.attrs.get("Mounts", [])
        for mount in mounts:
            destination = str(mount.get("Destination") or "").rstrip("/")
            if destination == str(root).rstrip("/"):
                source = str(mount.get("Source") or "").strip()
                if source:
                    return source
    except Exception:
        pass
    return str(root)


@dataclass(frozen=True)
class SplitPercentages:
    train: int
    val: int
    test: int

    def __post_init__(self) -> None:
        total = self.train + self.val + self.test
        if total != 100:
            raise ValueError("Split percentages must sum to 100.")
        for label, value in (("train", self.train), ("val", self.val), ("test", self.test)):
            if value < 0:
                raise ValueError(f"Split percentage '{label}' must be non-negative.")


@dataclass(frozen=True)
class ResolvedTrainingRequest:
    mode: str
    form_values: dict[str, str]
    split_percentages: SplitPercentages
    train_script: Path | None
    config_path: Path | None
    checkpoint_path: Path | None
    use_gpu: bool
    geometry_normalization: bool
    finetune_epochs: int | None
    early_stopping: EarlyStoppingConfig


def _render_template(value: str, values: dict[str, str]) -> str:
    return str(value or "").format(**values)


def _resolve_form_values(preset: TrainingPreset, form_values_raw: dict[str, str]) -> dict[str, str]:
    values = {str(key): str(value).strip() for key, value in (form_values_raw or {}).items() if str(key).strip()}
    normalized: dict[str, str] = {}
    root = workspace_root()
    for field in preset.form_fields:
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        raw = str(values.get(key) or "").strip()
        if not raw:
            raw = str(field.get("default") or "").strip()
        if field.get("required", True) and not raw:
            raise ValueError(f"Form field '{key}' is required for preset '{preset.profile_id}'.")
        if raw and (key.endswith("_path") or key.endswith("_dir") or key.endswith("_root")):
            resolved = resolve_workspace_path(raw)
            ensure_within(resolved, root, label=f"Form field '{key}'")
            raw = str(resolved)
        normalized[key] = raw
    for key, value in values.items():
        normalized.setdefault(key, value)
    return normalized


def resolve_training_request(
    *,
    preset: TrainingPreset,
    mode: str,
    form_values_raw: dict[str, str],
    train_percent: int,
    val_percent: int,
    test_percent: int,
    train_script_raw: str,
    config_path_raw: str,
    checkpoint_path_raw: str,
    use_gpu: bool,
    geometry_normalization: bool,
    finetune_epochs: int,
    early_stopping_enabled: bool,
    early_stopping_metric: str,
    early_stopping_mode: str,
    early_stopping_patience: int,
    early_stopping_min_delta: float,
) -> ResolvedTrainingRequest:
    if mode not in preset.modes:
        raise ValueError(
            f"Unsupported training mode '{mode}' for preset '{preset.profile_id}'. "
            f"Supported modes: {', '.join(sorted(preset.modes))}"
        )

    split_percentages = SplitPercentages(train=train_percent, val=val_percent, test=test_percent)
    form_values = _resolve_form_values(preset, form_values_raw)

    working_dir = preset.working_dir
    train_script = (
        resolve_workspace_path(train_script_raw, base_dir=working_dir)
        if str(train_script_raw or "").strip()
        else preset.default_train_script
    )
    if train_script is not None:
        ensure_within(train_script, workspace_root(), label="Train script")
        if not train_script.exists():
            raise ValueError(f"Train script not found: {train_script}")
        if str(train_script_raw or "").strip():
            ensure_within(train_script, preset.repo_path, label="Train script override")

    config_path = (
        resolve_workspace_path(config_path_raw, base_dir=working_dir)
        if str(config_path_raw or "").strip()
        else preset.default_train_config
    )
    if config_path is not None:
        ensure_within(config_path, workspace_root(), label="Config path")
        if not config_path.exists():
            raise ValueError(f"Config path not found: {config_path}")
        if str(config_path_raw or "").strip():
            ensure_within(config_path, preset.repo_path, label="Config override")

    checkpoint_path: Path | None = None
    resolved_finetune_epochs: int | None = None
    if mode == "finetune":
        checkpoint_raw = str(checkpoint_path_raw or "").strip()
        if checkpoint_raw:
            checkpoint_path = resolve_workspace_path(checkpoint_raw)
        elif preset.default_finetune_checkpoint is not None:
            checkpoint_path = preset.default_finetune_checkpoint
        else:
            raise ValueError("Finetune mode requires a checkpoint, but preset has no default checkpoint.")
        ensure_within(checkpoint_path, workspace_root(), label="Checkpoint path")
        if not checkpoint_path.exists():
            raise ValueError(f"Checkpoint not found: {checkpoint_path}")
        resolved_finetune_epochs = int(finetune_epochs)
        if resolved_finetune_epochs <= 0:
            raise ValueError("Finetune epochs must be greater than 0.")

    early_stopping_metric = str(early_stopping_metric or "").strip()
    if early_stopping_enabled and not early_stopping_metric:
        raise ValueError("Early stopping requires a monitored metric tag.")
    if early_stopping_mode not in {"min", "max"}:
        raise ValueError("Early stopping mode must be either 'min' or 'max'.")
    if int(early_stopping_patience) < 0:
        raise ValueError("Early stopping patience must be greater than or equal to 0.")
    if float(early_stopping_min_delta) < 0:
        raise ValueError("Early stopping min_delta must be greater than or equal to 0.")

    return ResolvedTrainingRequest(
        mode=mode,
        form_values=form_values,
        split_percentages=split_percentages,
        train_script=train_script,
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        use_gpu=use_gpu,
        geometry_normalization=bool(geometry_normalization),
        finetune_epochs=resolved_finetune_epochs,
        early_stopping=EarlyStoppingConfig(
            enabled=bool(early_stopping_enabled),
            metric=early_stopping_metric,
            mode=early_stopping_mode,
            patience=int(early_stopping_patience),
            min_delta=float(early_stopping_min_delta),
        ),
    )


def _build_render_values(*, preset: TrainingPreset, resolved: ResolvedTrainingRequest, run_dir: Path, artifacts_dir: Path, resolved_config_path: Path) -> dict[str, str]:
    values = dict(resolved.form_values)
    values.update(
        {
            "run_dir": str(run_dir),
            "run_dir_container": to_container_path(run_dir),
            "artifacts_dir": str(artifacts_dir),
            "artifacts_dir_container": to_container_path(artifacts_dir),
            "working_dir": str(preset.working_dir),
            "working_dir_container": to_container_path(preset.working_dir),
            "config_path": str(resolved.config_path) if resolved.config_path else "",
            "config_path_container": to_container_path(resolved.config_path) if resolved.config_path else "",
            "resolved_config_path": str(resolved_config_path),
            "resolved_config_path_container": to_container_path(resolved_config_path),
            "train_script": str(resolved.train_script) if resolved.train_script else "",
            "train_script_container": to_container_path(resolved.train_script) if resolved.train_script else "",
            "checkpoint_path": str(resolved.checkpoint_path) if resolved.checkpoint_path else "",
            "checkpoint_path_container": to_container_path(resolved.checkpoint_path) if resolved.checkpoint_path else "",
            "mode": resolved.mode,
        }
    )
    return values


def _list_point_files(root: Path) -> list[Path]:
    allowed_suffixes = {".npy", ".ply", ".xyz", ".txt", ".pts"}
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed_suffixes
    ]


def _normalize_with_reference(points: list[tuple[float, float, float]], centroid: list[float], scale: float) -> list[tuple[float, float, float]]:
    safe_scale = float(scale) if abs(float(scale)) > 1e-8 else 1.0
    normalized: list[tuple[float, float, float]] = []
    for x, y, z in points:
        normalized.append(
            (
                (float(x) - float(centroid[0])) / safe_scale,
                (float(y) - float(centroid[1])) / safe_scale,
                (float(z) - float(centroid[2])) / safe_scale,
            )
        )
    return normalized


def _centroid_and_scale(points: list[tuple[float, float, float]]) -> tuple[list[float], float]:
    if not points:
        return [0.0, 0.0, 0.0], 1.0
    centroid = [
        sum(item[axis] for item in points) / len(points)
        for axis in range(3)
    ]
    centered = [
        (
            float(item[0]) - centroid[0],
            float(item[1]) - centroid[1],
            float(item[2]) - centroid[2],
        )
        for item in points
    ]
    scale = max(max(abs(x), abs(y), abs(z)) for x, y, z in centered)
    if scale <= 1e-8:
        scale = 1.0
    return [float(centroid[0]), float(centroid[1]), float(centroid[2])], float(scale)


def _derive_target_key(partial_path: Path, *, mode: str, delimiter: str) -> str:
    partial_stem = partial_path.stem
    if mode == "parent_dir_name":
        return _canonical_sample_id(partial_path.parent.name)
    if mode == "prefix_before_delimiter" and delimiter:
        return _canonical_sample_id(partial_stem.split(delimiter, 1)[0])
    return _canonical_sample_id(partial_stem)


def _canonical_sample_id(raw_stem: str) -> str:
    stem = str(raw_stem or "").strip()
    if not stem:
        return stem
    stem = re.sub(r"_gt$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_partial_[0-9]+$", "", stem, flags=re.IGNORECASE)
    return stem


def _apply_preset_preprocess(
    *,
    preset: TrainingPreset,
    form_values: dict[str, str],
    run_dir: Path,
    logs_path: Path,
    geometry_normalization: bool,
) -> dict[str, str]:
    effective_values = dict(form_values)
    for index, step in enumerate(list(preset.preprocess or []), start=1):
        step_type = str(step.get("type") or "").strip()
        if step_type != "paired_geometry_normalization":
            append_log(logs_path, f"[training] Skip preprocess step #{index}: unsupported type '{step_type}'.\n")
            continue
        if not geometry_normalization:
            append_log(logs_path, f"[training] Skip preprocess step #{index}: geometry normalization disabled for run.\n")
            continue

        target_key = str(step.get("target_root_key") or "target_root").strip()
        partial_key = str(step.get("partial_root_key") or "partial_root").strip()
        output_target_key = str(step.get("output_target_key") or target_key).strip()
        output_partial_key = str(step.get("output_partial_key") or partial_key).strip()
        pairing_mode = str(step.get("pairing_mode") or "prefix_before_delimiter").strip()
        partial_delimiter = str(step.get("partial_delimiter") or "__").strip()

        target_root_raw = str(effective_values.get(target_key) or "").strip()
        partial_root_raw = str(effective_values.get(partial_key) or "").strip()
        if not target_root_raw or not partial_root_raw:
            append_log(
                logs_path,
                f"[training-warning] Preprocess step #{index} skipped: form fields '{target_key}'/'{partial_key}' are empty.\n",
            )
            continue

        target_root = resolve_workspace_path(target_root_raw)
        partial_root = resolve_workspace_path(partial_root_raw)
        ensure_within(target_root, workspace_root(), label="Preprocess target root")
        ensure_within(partial_root, workspace_root(), label="Preprocess partial root")
        if not target_root.exists() or not partial_root.exists():
            append_log(
                logs_path,
                f"[training-warning] Preprocess step #{index} skipped: dataset roots do not exist.\n",
            )
            continue

        output_root = run_dir / "preprocessed" / f"step_{index:02d}"
        out_target_root = output_root / "target"
        out_partial_root = output_root / "partial"
        out_target_root.mkdir(parents=True, exist_ok=True)
        out_partial_root.mkdir(parents=True, exist_ok=True)

        target_files = _list_point_files(target_root)
        partial_files = _list_point_files(partial_root)
        target_by_id = {_canonical_sample_id(path.stem): path for path in target_files}
        partial_groups: dict[str, list[Path]] = {}
        for partial_path in partial_files:
            target_id = _derive_target_key(
                partial_path,
                mode=pairing_mode,
                delimiter=partial_delimiter,
            )
            if target_id not in target_by_id:
                fallback_id = _canonical_sample_id(partial_path.stem)
                if fallback_id in target_by_id:
                    target_id = fallback_id
            partial_groups.setdefault(target_id, []).append(partial_path)

        processed_targets = 0
        processed_partials = 0
        skipped_partials = 0

        for target_id, target_path in target_by_id.items():
            partials = partial_groups.get(target_id) or []
            if not partials:
                continue
            target_points = load_points(target_path)
            centroid, scale = _centroid_and_scale(target_points)
            target_norm = _normalize_with_reference(target_points, centroid, scale)
            target_out = out_target_root / target_path.relative_to(target_root)
            save_points(target_out, target_norm)
            processed_targets += 1

            for partial_path in partials:
                partial_points = load_points(partial_path)
                partial_norm = _normalize_with_reference(partial_points, centroid, scale)
                partial_out = out_partial_root / partial_path.relative_to(partial_root)
                save_points(partial_out, partial_norm)
                processed_partials += 1

        for target_id, partials in partial_groups.items():
            if target_id in target_by_id:
                continue
            skipped_partials += len(partials)

        effective_values[output_target_key] = str(out_target_root)
        effective_values[output_partial_key] = str(out_partial_root)
        append_log(
            logs_path,
            (
                "[training] Preprocess paired normalization completed: "
                f"targets={processed_targets}, partials={processed_partials}, "
                f"partials_without_target={skipped_partials}, mode={pairing_mode}.\n"
            ),
        )
    return effective_values


def _resolve_command(*, preset: TrainingPreset, resolved: ResolvedTrainingRequest, render_values: dict[str, str]) -> list[str]:
    if preset.command_template:
        return [_render_template(token, render_values) for token in preset.command_template]

    if resolved.train_script is None:
        raise ValueError("Preset must define either command_template or default_train_script/train_script override.")

    script_container_path = Path(to_container_path(resolved.train_script))
    working_dir_container_path = Path(to_container_path(preset.working_dir))
    try:
        script_arg = str(script_container_path.relative_to(working_dir_container_path))
    except ValueError:
        script_arg = str(script_container_path)

    command = ["python", script_arg]
    if resolved.config_path is not None:
        command.extend(["--config", render_values["resolved_config_path_container"]])
    if resolved.mode == "finetune" and resolved.checkpoint_path is not None:
        contract = dict(getattr(preset, "finetune_contract", {}) or {})
        cli_checkpoint_arg = str(contract.get("cli_checkpoint_arg") or "").strip()
        if cli_checkpoint_arg:
            command.extend([cli_checkpoint_arg, render_values["checkpoint_path_container"]])
    if preset.args_template:
        command.extend([_render_template(item, render_values) for item in preset.args_template])
    return command


def _resolve_checkpoint_search_roots(*, preset: TrainingPreset, render_values: dict[str, str], run_dir: Path) -> list[Path]:
    roots: list[Path] = []
    for item in preset.checkpoint_search_roots:
        rendered = _render_template(item, render_values).strip()
        if not rendered:
            continue
        path = resolve_workspace_path(rendered)
        ensure_within(path, workspace_root(), label="Checkpoint search root")
        roots.append(path)
    return roots or [run_dir]


def _materialize_checkpoints_into_run_dir(
    *,
    checkpoint_search_roots: list[Path],
    checkpoint_priority: list[str],
    run_dir: Path,
    logs_path: Path,
) -> list[Path]:
    target_root = run_dir / "artifacts" / "checkpoints"
    target_root.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    seen_sources: set[Path] = set()
    counter = 0
    for pattern in checkpoint_priority:
        for root in checkpoint_search_roots:
            if not root.exists():
                continue
            for source in root.glob(pattern):
                if not source.is_file():
                    continue
                resolved = source.resolve()
                if resolved in seen_sources:
                    continue
                seen_sources.add(resolved)
                counter += 1
                suffix = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
                destination = target_root / f"{counter:04d}_{suffix}_{source.name}"
                shutil.copy2(source, destination)
                copied.append(destination)

    if copied:
        append_log(
            logs_path,
            f"[training] Copied {len(copied)} checkpoint file(s) into {target_root}.\n",
        )
    return copied


def _get_nested(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in [chunk.strip() for chunk in str(dotted_path or "").split(".") if chunk.strip()]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _set_nested(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    current: dict[str, Any] = payload
    parts = [chunk.strip() for chunk in str(dotted_path or "").split(".") if chunk.strip()]
    if not parts:
        return
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _build_dataset_pairs(
    *,
    target_root: Path,
    partial_root: Path,
    pairing_mode: str,
    partial_delimiter: str,
) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    target_files = _list_point_files(target_root)
    partial_files = _list_point_files(partial_root)
    target_by_id = {_canonical_sample_id(path.stem): path for path in target_files}
    partial_groups: dict[str, list[Path]] = {}
    for partial_path in partial_files:
        target_id = _derive_target_key(
            partial_path,
            mode=pairing_mode,
            delimiter=partial_delimiter,
        )
        if target_id not in target_by_id:
            fallback_id = _canonical_sample_id(partial_path.stem)
            if fallback_id in target_by_id:
                target_id = fallback_id
        partial_groups.setdefault(target_id, []).append(partial_path)
    return target_by_id, partial_groups


def _hash_dataset_inputs(
    *,
    format_name: str,
    exporter_version: str,
    target_root: Path,
    partial_root: Path,
    pairing_mode: str,
    partial_delimiter: str,
    geometry_normalization: bool,
    split_percentages: SplitPercentages,
    requested_gt_points: int | None,
) -> str:
    payload = {
        "format": format_name,
        "exporter_version": exporter_version,
        "target_root": str(target_root.resolve()),
        "partial_root": str(partial_root.resolve()),
        "pairing_mode": pairing_mode,
        "partial_delimiter": partial_delimiter,
        "geometry_normalization": bool(geometry_normalization),
        "requested_gt_points": int(requested_gt_points) if requested_gt_points is not None else None,
        "split_percentages": {
            "train": int(split_percentages.train),
            "val": int(split_percentages.val),
            "test": int(split_percentages.test),
        },
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _allocate_split_sizes(total: int, split_percentages: SplitPercentages) -> dict[str, int]:
    if total <= 0:
        return {"train": 0, "val": 0, "test": 0}
    labels = ("train", "val", "test")
    pcts = {
        "train": float(split_percentages.train),
        "val": float(split_percentages.val),
        "test": float(split_percentages.test),
    }
    raw = {label: (total * pcts[label] / 100.0) for label in labels}
    counts = {label: int(raw[label]) for label in labels}
    assigned = sum(counts.values())
    remainder = total - assigned
    if remainder > 0:
        order = sorted(labels, key=lambda label: (raw[label] - counts[label], pcts[label]), reverse=True)
        idx = 0
        while remainder > 0:
            label = order[idx % len(order)]
            counts[label] += 1
            remainder -= 1
            idx += 1
    return counts


def _export_completion3d_h5(
    *,
    target_by_id: dict[str, Path],
    partial_groups: dict[str, list[Path]],
    export_root: Path,
    geometry_normalization: bool,
    split_percentages: SplitPercentages,
    requested_gt_points: int | None,
) -> dict[str, str]:
    try:
        import numpy as np
        import h5py
    except Exception as exc:
        raise RuntimeError("completion3d_h5 exporter requires numpy and h5py in orchestrator runtime.") from exc

    dataset_root = export_root / "Completion3D"
    dataset_root.mkdir(parents=True, exist_ok=True)

    taxonomy_id = "03001627"
    taxonomy_name = "custom"
    category = {
        "taxonomy_id": taxonomy_id,
        "taxonomy_name": taxonomy_name,
        "train": [],
        "val": [],
        "test": [],
    }

    split_dirs: dict[str, tuple[Path, Path]] = {}
    for split in ("train", "val", "test"):
        partial_base = dataset_root / split / "partial" / taxonomy_id
        gt_base = dataset_root / split / "gt" / taxonomy_id
        partial_base.mkdir(parents=True, exist_ok=True)
        gt_base.mkdir(parents=True, exist_ok=True)
        split_dirs[split] = (partial_base, gt_base)

    exported_samples_count = 0
    gt_n_points: int | None = None
    samples: list[tuple[str, Any, Any]] = []

    for target_id, target_path in target_by_id.items():
        partials = partial_groups.get(target_id) or []
        if not partials:
            continue
        target_points = load_points(target_path)
        centroid = [0.0, 0.0, 0.0]
        scale = 1.0
        if geometry_normalization:
            centroid, scale = _centroid_and_scale(target_points)
            target_points = _normalize_with_reference(target_points, centroid, scale)

        target_points_np = np.asarray(target_points, dtype=np.float32)
        if target_points_np.ndim != 2:
            raise ValueError(
                f"Target cloud '{target_path}' must be rank-2 array [N,3], got shape={tuple(target_points_np.shape)}."
            )
        if requested_gt_points is not None:
            current = int(target_points_np.shape[0])
            if current > requested_gt_points:
                target_points_np = target_points_np[:requested_gt_points]
            elif current < requested_gt_points:
                if current <= 0:
                    raise ValueError(f"Target cloud '{target_path}' is empty and cannot be resized.")
                needed = requested_gt_points - current
                reps = (needed + current - 1) // current
                padded = np.tile(target_points_np, (reps, 1))[:needed]
                target_points_np = np.concatenate([target_points_np, padded], axis=0)
        current_gt_n_points = int(target_points_np.shape[0])
        if gt_n_points is None:
            gt_n_points = current_gt_n_points
        elif current_gt_n_points != gt_n_points:
            raise ValueError(
                "completion3d_h5 exporter requires a fixed GT point count across targets. "
                f"Found both {gt_n_points} and {current_gt_n_points} points."
            )

        for idx, partial_path in enumerate(partials):
            partial_id = f"{target_id}__{idx:03d}"
            partial_points = load_points(partial_path)
            if geometry_normalization:
                partial_points = _normalize_with_reference(partial_points, centroid, scale)
            partial_points_np = np.asarray(partial_points, dtype=np.float32)
            samples.append((partial_id, partial_points_np, target_points_np))
            exported_samples_count += 1

    if exported_samples_count <= 0:
        raise ValueError(
            "Dataset export produced 0 samples. Check pairing_mode and dataset roots: "
            "no partial clouds were matched to target clouds."
        )
    if gt_n_points is None or int(gt_n_points) <= 0:
        raise ValueError("Dataset export could not infer GT point count for N_POINTS.")
    samples.sort(key=lambda item: item[0])
    split_sizes = _allocate_split_sizes(len(samples), split_percentages)
    if int(split_percentages.val) > 0 and int(split_sizes.get("val", 0)) <= 0:
        raise ValueError(
            "Dataset split produced 0 validation samples. Increase val_percent or use a larger dataset."
        )
    split_sequence: list[str] = []
    for split in ("train", "val", "test"):
        split_sequence.extend([split] * int(split_sizes[split]))
    for idx, (partial_id, partial_points_np, target_points_np) in enumerate(samples):
        split = split_sequence[idx] if idx < len(split_sequence) else "train"
        partial_base, gt_base = split_dirs[split]
        partial_h5 = partial_base / f"{partial_id}.h5"
        with h5py.File(str(partial_h5), "w") as out:
            out.create_dataset("data", data=partial_points_np)
        gt_path = gt_base / f"{partial_id}.h5"
        with h5py.File(str(gt_path), "w") as out:
            out.create_dataset("data", data=target_points_np)
        category[split].append(partial_id)

    category_file_path = dataset_root / "Completion3D.json"
    category_file_path.write_text(json.dumps([category], ensure_ascii=True, indent=2), encoding="utf-8")

    dataset_config_path = export_root / "dataset_config_completion3d.yaml"
    dataset_config_payload = {
        "NAME": "Completion3D",
        "CATEGORY_FILE_PATH": str(category_file_path.as_posix()),
        "N_POINTS": int(gt_n_points),
        "PARTIAL_POINTS_PATH": str((dataset_root / "%s" / "partial" / "%s" / "%s.h5").as_posix()),
        "COMPLETE_POINTS_PATH": str((dataset_root / "%s" / "gt" / "%s" / "%s.h5").as_posix()),
        "CARS": False,
    }
    dataset_config_path.write_text(yaml.safe_dump(dataset_config_payload, sort_keys=False), encoding="utf-8")

    split_counts = {
        "train": int(len(category["train"])),
        "val": int(len(category["val"])),
        "test": int(len(category["test"])),
    }
    sample_counts = dict(split_counts)

    return {
        "dataset_root": str(dataset_root),
        "category_file_path": str(category_file_path),
        "partial_points_path_pattern": str((dataset_root / "%s" / "partial" / "%s" / "%s.h5").as_posix()),
        "complete_points_path_pattern": str((dataset_root / "%s" / "gt" / "%s" / "%s.h5").as_posix()),
        "dataset_config_path": str(dataset_config_path),
        "gt_n_points": int(gt_n_points),
        "exported_samples_count": str(exported_samples_count),
        "split_counts": split_counts,
        "sample_counts": sample_counts,
    }


def _run_dataset_export(
    *,
    preset: TrainingPreset,
    effective_form_values: dict[str, str],
    run_dir: Path,
    logs_path: Path,
    geometry_normalization: bool,
    split_percentages: SplitPercentages,
) -> dict[str, Any]:
    dataset_export = dict(getattr(preset, "dataset_export", {}) or {})
    format_name = str(dataset_export.get("format") or "").strip()
    if not format_name:
        return {}
    if format_name != "completion3d_h5":
        raise ValueError(f"Unsupported dataset export format: {format_name}")

    contract = dict(getattr(preset, "dataset_contract", {}) or {})
    target_key = str(contract.get("target_root_key") or "target_root").strip()
    partial_key = str(contract.get("partial_root_key") or "partial_root").strip()
    pairing_mode = str(contract.get("pairing_mode") or "parent_dir_name").strip()
    partial_delimiter = str(contract.get("partial_delimiter") or "__").strip()
    requested_gt_points_raw = str(dataset_export.get("gt_points_count") or "").strip()
    requested_gt_points: int | None = None
    if requested_gt_points_raw:
        try:
            requested_gt_points = int(requested_gt_points_raw)
        except ValueError as exc:
            raise ValueError(f"dataset_export.gt_points_count must be an integer, got: {requested_gt_points_raw}") from exc
        if requested_gt_points <= 0:
            raise ValueError("dataset_export.gt_points_count must be greater than 0.")

    target_root_raw = str(effective_form_values.get(target_key) or "").strip()
    partial_root_raw = str(effective_form_values.get(partial_key) or "").strip()
    if not target_root_raw or not partial_root_raw:
        raise ValueError(f"Dataset export requires form values '{target_key}' and '{partial_key}'.")

    target_root = resolve_workspace_path(target_root_raw)
    partial_root = resolve_workspace_path(partial_root_raw)
    ensure_within(target_root, workspace_root(), label="Dataset export target root")
    ensure_within(partial_root, workspace_root(), label="Dataset export partial root")
    if not target_root.exists() or not partial_root.exists():
        raise ValueError("Dataset export roots do not exist.")

    has_pair_norm_preprocess = any(
        str((step or {}).get("type") or "").strip() == "paired_geometry_normalization"
        for step in list(getattr(preset, "preprocess", []) or [])
    )
    export_geometry_normalization = bool(geometry_normalization) and not has_pair_norm_preprocess
    exporter_version = COMPLETION3D_EXPORTER_VERSION if format_name == "completion3d_h5" else "v1"
    dataset_hash = _hash_dataset_inputs(
        format_name=format_name,
        exporter_version=exporter_version,
        target_root=target_root,
        partial_root=partial_root,
        pairing_mode=pairing_mode,
        partial_delimiter=partial_delimiter,
        geometry_normalization=export_geometry_normalization,
        split_percentages=split_percentages,
        requested_gt_points=requested_gt_points,
    )
    cache_root = training_runs_root() / preset.model_id / "dataset_cache" / dataset_hash
    cache_hit = cache_root.exists()
    cache_root.mkdir(parents=True, exist_ok=True)

    def _read_counts_from_category_file(category_path: Path) -> tuple[dict[str, int], dict[str, int]]:
        default_counts = {"train": 0, "val": 0, "test": 0}
        try:
            payload = json.loads(category_path.read_text(encoding="utf-8"))
            first = payload[0] if isinstance(payload, list) and payload else {}
            if not isinstance(first, dict):
                return dict(default_counts), dict(default_counts)
            split_counts = {
                "train": int(len(first.get("train") or [])),
                "val": int(len(first.get("val") or [])),
                "test": int(len(first.get("test") or [])),
            }
            return split_counts, dict(split_counts)
        except Exception:
            return dict(default_counts), dict(default_counts)

    def _is_valid_completion3d_cache(root: Path) -> bool:
        category = root / "Completion3D" / "Completion3D.json"
        cfg = root / "dataset_config_completion3d.yaml"
        if not category.exists() or not cfg.exists():
            return False
        for split in ("train", "val", "test"):
            partial_dir = root / "Completion3D" / split / "partial" / "03001627"
            gt_dir = root / "Completion3D" / split / "gt" / "03001627"
            if not partial_dir.exists() or not gt_dir.exists():
                return False
            if not any(partial_dir.glob("*.h5")) or not any(gt_dir.glob("*.h5")):
                return False
        return True

    if cache_hit and not _is_valid_completion3d_cache(cache_root):
        append_log(
            logs_path,
            f"[training-warning] Dataset cache {dataset_hash} is incomplete/corrupted; rebuilding.\n",
        )
        try:
            shutil.rmtree(cache_root)
        except Exception:
            pass
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_hit = False

    if not cache_hit:
        target_by_id, partial_groups = _build_dataset_pairs(
            target_root=target_root,
            partial_root=partial_root,
            pairing_mode=pairing_mode,
            partial_delimiter=partial_delimiter,
        )
        export_payload = _export_completion3d_h5(
            target_by_id=target_by_id,
            partial_groups=partial_groups,
            export_root=cache_root,
            geometry_normalization=export_geometry_normalization,
            split_percentages=split_percentages,
            requested_gt_points=requested_gt_points,
        )
        if int(str(export_payload.get("exported_samples_count") or "0")) <= 0:
            sample_target_ids = list(target_by_id.keys())[:5]
            sample_partial_ids = []
            for partial_id in list(partial_groups.keys())[:5]:
                sample_partial_ids.append(partial_id)
            append_log(
                logs_path,
                "[training-warning] Export produced no samples. "
                f"pairing_mode={pairing_mode}; sample_target_ids={sample_target_ids}; "
                f"sample_derived_partial_ids={sample_partial_ids}\n",
            )
    else:
        category_file_path = cache_root / "Completion3D" / "Completion3D.json"
        split_counts, sample_counts = _read_counts_from_category_file(category_file_path)
        export_payload = {
            "dataset_root": str(cache_root / "Completion3D"),
            "category_file_path": str(category_file_path),
            "partial_points_path_pattern": str((cache_root / "Completion3D" / "%s" / "partial" / "%s" / "%s.h5").as_posix()),
            "complete_points_path_pattern": str((cache_root / "Completion3D" / "%s" / "gt" / "%s" / "%s.h5").as_posix()),
            "dataset_config_path": str(cache_root / "dataset_config_completion3d.yaml"),
            "exported_samples_count": "unknown",
            "split_counts": split_counts,
            "sample_counts": sample_counts,
        }

    append_log(
        logs_path,
        f"[training] Dataset export {format_name}@{exporter_version}: {'cache-hit' if cache_hit else 'cache-miss'} ({dataset_hash}). samples={export_payload.get('exported_samples_count', 'unknown')}\n",
    )
    return {
        "dataset_export_format": format_name,
        "dataset_export_version": exporter_version,
        "dataset_hash": dataset_hash,
        "dataset_cache_path": str(cache_root),
        "dataset_cache_hit": cache_hit,
        **export_payload,
    }


def _apply_config_patch_rules(*, preset: TrainingPreset, resolved_config_path: Path, render_values: dict[str, str]) -> None:
    if not resolved_config_path.exists():
        return
    rules = list(getattr(preset, "config_patch_rules", []) or [])
    if not rules:
        return
    payload = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8")) or {}
    for rule in rules:
        key_path = str(rule.get("key") or "").strip()
        value_template = str(rule.get("value") or "").strip()
        if not key_path or not value_template:
            continue
        _set_nested(payload, key_path, _render_template(value_template, render_values))
    resolved_config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def build_run_artifacts(*, preset: TrainingPreset, resolved: ResolvedTrainingRequest, run_id: str) -> dict[str, Any]:
    run_dir = training_runs_root() / preset.model_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    resolved_placeholder_values = {"run_dir": str(run_dir)}
    artifacts_dir_raw = _render_template(preset.artifacts_dir, resolved_placeholder_values)
    artifacts_dir = resolve_workspace_path(artifacts_dir_raw)
    ensure_within(artifacts_dir, workspace_root(), label="Artifacts directory")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    logs_path = run_dir / "run.log"
    request_path = run_dir / "request_snapshot.json"
    resolved_config_path = run_dir / "resolved_config.yaml"
    metrics_path = run_dir / "metrics.json"
    metrics_history_path = metric_history_path_for_run(run_dir)
    early_stopping_state_path = early_stopping_state_path_for_run(run_dir)

    if resolved.config_path is not None:
        resolved_config_path.write_text(resolved.config_path.read_text(encoding="utf-8"), encoding="utf-8")

    effective_form_values = _apply_preset_preprocess(
        preset=preset,
        form_values=resolved.form_values,
        run_dir=run_dir,
        logs_path=logs_path,
        geometry_normalization=resolved.geometry_normalization,
    )
    dataset_export_meta = _run_dataset_export(
        preset=preset,
        effective_form_values=effective_form_values,
        run_dir=run_dir,
        logs_path=logs_path,
        geometry_normalization=resolved.geometry_normalization,
        split_percentages=resolved.split_percentages,
    )

    effective_resolved = ResolvedTrainingRequest(
        mode=resolved.mode,
        form_values=effective_form_values,
        split_percentages=resolved.split_percentages,
        train_script=resolved.train_script,
        config_path=resolved.config_path,
        checkpoint_path=resolved.checkpoint_path,
        use_gpu=resolved.use_gpu,
        geometry_normalization=resolved.geometry_normalization,
        finetune_epochs=resolved.finetune_epochs,
        early_stopping=resolved.early_stopping,
    )
    render_values = _build_render_values(
        preset=preset,
        resolved=effective_resolved,
        run_dir=run_dir,
        artifacts_dir=artifacts_dir,
        resolved_config_path=resolved_config_path,
    )
    render_values.update(
        {
            "export_dataset_root": str(dataset_export_meta.get("dataset_root") or ""),
            "export_category_file_path": str(dataset_export_meta.get("category_file_path") or ""),
            "export_partial_points_path_pattern": str(dataset_export_meta.get("partial_points_path_pattern") or ""),
            "export_complete_points_path_pattern": str(dataset_export_meta.get("complete_points_path_pattern") or ""),
            "export_dataset_config_path": str(dataset_export_meta.get("dataset_config_path") or ""),
        }
    )
    _apply_config_patch_rules(
        preset=preset,
        resolved_config_path=resolved_config_path,
        render_values=render_values,
    )
    command = _resolve_command(preset=preset, resolved=resolved, render_values=render_values)
    env_overrides = {
        key: _render_template(value, render_values)
        for key, value in preset.env_template.items()
    }

    checkpoint_search_roots = _resolve_checkpoint_search_roots(
        preset=preset,
        render_values=render_values,
        run_dir=run_dir,
    )

    split_counts = dict(dataset_export_meta.get("split_counts") or {"train": 0, "val": 0, "test": 0})
    sample_counts = dict(dataset_export_meta.get("sample_counts") or {"train": 0, "val": 0, "test": 0})

    snapshot = {
        "profile_id": preset.profile_id,
        "model_id": preset.model_id,
        "mode": resolved.mode,
        "form_values": effective_form_values,
        "split_percentages": {
            "train": resolved.split_percentages.train,
            "val": resolved.split_percentages.val,
            "test": resolved.split_percentages.test,
        },
        "split_counts": split_counts,
        "sample_counts": sample_counts,
        "train_script": to_workspace_relative(resolved.train_script) if resolved.train_script else "",
        "config_path": to_workspace_relative(resolved.config_path) if resolved.config_path else "",
        "resolved_config_path": to_workspace_relative(resolved_config_path) if resolved.config_path else "",
        "checkpoint_path": to_workspace_relative(resolved.checkpoint_path) if resolved.checkpoint_path else "",
        "finetune_epochs": resolved.finetune_epochs,
        "use_gpu": resolved.use_gpu,
        "geometry_normalization": resolved.geometry_normalization,
        "dataset_export_format": dataset_export_meta.get("dataset_export_format"),
        "dataset_export_version": dataset_export_meta.get("dataset_export_version"),
        "dataset_hash": dataset_export_meta.get("dataset_hash"),
        "dataset_cache_path": to_workspace_relative(Path(dataset_export_meta["dataset_cache_path"])) if dataset_export_meta.get("dataset_cache_path") else "",
        "dataset_cache_hit": bool(dataset_export_meta.get("dataset_cache_hit", False)),
        "exported_samples_count": int(str(dataset_export_meta.get("exported_samples_count") or "0")) if str(dataset_export_meta.get("exported_samples_count") or "").isdigit() else dataset_export_meta.get("exported_samples_count"),
        "early_stopping": {
            "enabled": resolved.early_stopping.enabled,
            "metric": resolved.early_stopping.metric,
            "mode": resolved.early_stopping.mode,
            "patience": resolved.early_stopping.patience,
            "min_delta": resolved.early_stopping.min_delta,
        },
    }
    request_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
    write_early_stopping_state(early_stopping_state_path, default_early_stopping_state(resolved.early_stopping))

    return {
        "run_dir": run_dir,
        "artifacts_dir": artifacts_dir,
        "logs_path": logs_path,
        "request_path": request_path,
        "resolved_config_path": resolved_config_path,
        "metrics_path": metrics_path,
        "metrics_history_path": metrics_history_path,
        "early_stopping_state_path": early_stopping_state_path,
        "command": command,
        "env_overrides": env_overrides,
        "checkpoint_search_roots": checkpoint_search_roots,
    }


def create_training_run_record(*, run_id: str, preset: TrainingPreset, resolved: ResolvedTrainingRequest, artifacts: dict[str, Any]) -> TrainingRun:
    run = TrainingRun(
        id=run_id,
        profile_id=preset.profile_id,
        model_id=preset.model_id,
        task_type=preset.task_type,
        status="pending",
        mode=resolved.mode,
        dataset_root=json.dumps(resolved.form_values, ensure_ascii=True),
        train_script=to_workspace_relative(resolved.train_script) if resolved.train_script else "",
        config_path=to_workspace_relative(resolved.config_path) if resolved.config_path else "",
        resolved_config_path=to_workspace_relative(artifacts["resolved_config_path"]) if resolved.config_path else "",
        run_dir=to_workspace_relative(artifacts["run_dir"]),
        logs_path=to_workspace_relative(artifacts["logs_path"]),
        metrics_path=to_workspace_relative(artifacts["metrics_path"]),
        command_json=json.dumps(artifacts["command"]),
        best_checkpoint_path=None,
        error_message=None,
        started_at=None,
        finished_at=None,
    )
    db = SessionLocal()
    try:
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    finally:
        db.close()


def _update_run(run_id: str, **fields: Any) -> None:
    db = SessionLocal()
    try:
        run = db.get(TrainingRun, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        db.add(run)
        db.commit()
    finally:
        db.close()


def cancel_training_run(run_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        run = db.get(TrainingRun, run_id)
        if run is None:
            raise FileNotFoundError(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            return {"status": run.status, "already_final": True}
    finally:
        db.close()

    with _ACTIVE_RUNS_LOCK:
        active = _ACTIVE_RUNS.get(run_id)
        if active:
            active["cancel_requested"] = True
            try:
                active["container"].stop(timeout=10)
                return {"status": "cancel_requested", "already_final": False}
            except Exception as exc:
                return {"status": "cancel_failed", "already_final": False, "error": str(exc)}

    _update_run(run_id, status="cancelled", finished_at=utc_now(), error_message="Cancelled by user.")
    return {"status": "cancelled", "already_final": False}


def start_training_run(*, preset: TrainingPreset, resolved: ResolvedTrainingRequest, artifacts: dict[str, Any], run_id: str) -> None:
    logs_path = artifacts["logs_path"]
    command = artifacts["command"]
    env_overrides = dict(artifacts.get("env_overrides") or {})
    run_dir = artifacts["run_dir"]
    metrics_path = artifacts["metrics_path"]
    metrics_history_path = artifacts["metrics_history_path"]
    early_stopping_state_path = artifacts["early_stopping_state_path"]
    checkpoint_search_roots = [Path(item) for item in artifacts.get("checkpoint_search_roots", [run_dir])]
    if resolved.mode == "finetune":
        contract = dict(getattr(preset, "finetune_contract", {}) or {})
        if bool(contract.get("resume_via_experiment", False)):
            resolved_config_path = Path(artifacts.get("resolved_config_path"))
            # PoinTr-style resume writes checkpoints under:
            # <working_dir>/experiments/<config_stem>/<run_id>/default
            run_scoped_experiment_dir = (
                preset.working_dir
                / "experiments"
                / resolved_config_path.stem
                / run_dir.name
                / "default"
            ).resolve()
            if run_scoped_experiment_dir not in checkpoint_search_roots:
                checkpoint_search_roots = [run_scoped_experiment_dir, *checkpoint_search_roots]

    def _runner() -> None:
        _update_run(run_id, status="running", started_at=utc_now())
        append_log(logs_path, f"[training] Starting run {run_id}\n")
        append_log(logs_path, f"[training] image={preset.image_tag}\n")
        append_log(logs_path, f"[training] command={' '.join(shlex.quote(item) for item in command)}\n")
        if resolved.mode == "finetune":
            contract = dict(getattr(preset, "finetune_contract", {}) or {})
            if not str(contract.get("config_resume_path") or "").strip() or not str(contract.get("config_model_path") or "").strip():
                append_log(
                    logs_path,
                    "[training-warning] finetune_contract has no config_resume_path/config_model_path. "
                    "Model may run with finetune horizon but without resume-from-checkpoint semantics.\n",
                )
        from orchestrator.onboarding.docker_ops import docker_image_exists

        if not docker_image_exists(preset.image_tag):
            message = (
                f"Docker image not found: {preset.image_tag}. "
                "Build and smoke-check the model first via onboarding."
            )
            append_log(logs_path, f"[training-error] {message}\n")
            _update_run(run_id, status="failed", finished_at=utc_now(), error_message=message)
            return

        container = None
        early_stop_requested = threading.Event()
        early_stop_completed = threading.Event()
        monitor_stop = threading.Event()
        cancel_requested = False
        try:
            import docker
            from docker.errors import DockerException
            from docker.types import DeviceRequest

            client = docker.from_env()
            wrapped_command = [
                "python",
                "/app/orchestrator/training/runtime_shims/launch_training.py",
                *command,
            ]
            env = {
                "PYTHONUNBUFFERED": "1",
                "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python",
                "PYTHONPATH": "/app/orchestrator/training/runtime_shims:/app",
                "PCPP_METRICS_HISTORY_PATH": to_container_path(metrics_history_path),
                "PCPP_TRAINING_MODE": resolved.mode,
                "PCPP_GEOMETRY_NORMALIZATION": "1" if resolved.geometry_normalization else "0",
                **env_overrides,
            }
            native_extensions = list(getattr(preset, "native_extensions", []) or [])
            if native_extensions:
                env["PCPP_NATIVE_EXTENSIONS_JSON"] = json.dumps(native_extensions, ensure_ascii=True)
            if resolved.mode == "finetune" and resolved.finetune_epochs and resolved.checkpoint_path is not None:
                env["PCPP_FINETUNE_EPOCHS"] = str(resolved.finetune_epochs)
                env["PCPP_FINETUNE_CHECKPOINT_PATH"] = to_container_path(resolved.checkpoint_path)
                if resolved.config_path is not None:
                    env["PCPP_FINETUNE_CONFIG_PATH"] = to_container_path(artifacts["resolved_config_path"])
                env["PCPP_FINETUNE_CONTRACT_JSON"] = json.dumps(
                    dict(getattr(preset, "finetune_contract", {}) or {}),
                    ensure_ascii=True,
                )

            device_requests = None
            if resolved.use_gpu:
                env["NVIDIA_VISIBLE_DEVICES"] = "all"
                env["NVIDIA_DRIVER_CAPABILITIES"] = "compute,utility"
                device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

            container = client.containers.run(
                preset.image_tag,
                command=wrapped_command,
                working_dir=to_container_path(preset.working_dir),
                environment=env,
                device_requests=device_requests,
                volumes={
                    discover_workspace_bind_source(): {
                        "bind": "/app",
                        "mode": "rw",
                    },
                },
                detach=True,
                remove=False,
            )
            with _ACTIVE_RUNS_LOCK:
                _ACTIVE_RUNS[run_id] = {"container": container, "cancel_requested": False}

            def _monitor_early_stopping() -> None:
                if not resolved.early_stopping.enabled:
                    return
                while not monitor_stop.is_set():
                    state = evaluate_early_stopping(resolved.early_stopping, metrics_history_path)
                    write_early_stopping_state(early_stopping_state_path, state)
                    if state.triggered and not early_stop_requested.is_set():
                        early_stop_requested.set()
                        append_log(logs_path, f"[training] Early stopping triggered: {state.stop_reason or 'threshold reached'}\n")
                        try:
                            container.stop(timeout=10)
                        except DockerException as exc:
                            append_log(logs_path, f"[training-warning] Failed to stop container for early stopping: {exc}\n")
                    monitor_stop.wait(2.0)

            monitor_thread = threading.Thread(target=_monitor_early_stopping, daemon=True)
            monitor_thread.start()
            for line in container.logs(stream=True, follow=True):
                append_log(logs_path, line.decode("utf-8", errors="replace"))

            result = container.wait()
            exit_code = int(result.get("StatusCode", 1))
            with _ACTIVE_RUNS_LOCK:
                active = _ACTIVE_RUNS.get(run_id) or {}
                cancel_requested = bool(active.get("cancel_requested"))
            monitor_stop.set()
            final_early_stopping_state = evaluate_early_stopping(resolved.early_stopping, metrics_history_path)
            if early_stop_requested.is_set():
                final_early_stopping_state.triggered = True
                final_early_stopping_state.stopped_early = True
                final_early_stopping_state.stop_reason = (
                    final_early_stopping_state.stop_reason or "Training stopped by orchestrator early stopping."
                )
                early_stop_completed.set()
            write_early_stopping_state(early_stopping_state_path, final_early_stopping_state)

            if cancel_requested:
                append_log(logs_path, "[training] Cancelled by user request.\n")
                _update_run(
                    run_id,
                    status="cancelled",
                    finished_at=utc_now(),
                    error_message="Cancelled by user.",
                )
                return

            if exit_code != 0 and not early_stop_completed.is_set():
                message = f"Training container exited with code {exit_code}"
                append_log(logs_path, f"[training-error] {message}\n")
                _update_run(run_id, status="failed", finished_at=utc_now(), error_message=message)
                return

            copied_checkpoints = _materialize_checkpoints_into_run_dir(
                checkpoint_search_roots=checkpoint_search_roots,
                checkpoint_priority=list(preset.checkpoint_priority or []),
                run_dir=run_dir,
                logs_path=logs_path,
            )
            best_checkpoint = resolve_best_checkpoint(
                [run_dir / "artifacts" / "checkpoints"],
                preset.checkpoint_priority,
                fallback_checkpoint=(copied_checkpoints[0] if copied_checkpoints else None),
            )
            if best_checkpoint is None:
                message = "Training completed, but no checkpoint matching preset rules was found."
                append_log(logs_path, f"[training-error] {message}\n")
                _update_run(run_id, status="failed", finished_at=utc_now(), error_message=message)
                return

            metrics_payload = {
                "best_checkpoint_path": to_workspace_relative(best_checkpoint),
                "run_dir": to_workspace_relative(run_dir),
                "completed_at": utc_now().isoformat(),
                "metrics_history_path": to_workspace_relative(metrics_history_path),
                "early_stopping_state_path": to_workspace_relative(early_stopping_state_path),
                "early_stopping": {
                    "enabled": final_early_stopping_state.enabled,
                    "supported": final_early_stopping_state.supported,
                    "triggered": final_early_stopping_state.triggered,
                    "stopped_early": final_early_stopping_state.stopped_early,
                    "stop_reason": final_early_stopping_state.stop_reason,
                    "monitor_metric": final_early_stopping_state.monitor_metric,
                    "best_metric_value": final_early_stopping_state.best_metric_value,
                    "best_metric_step": final_early_stopping_state.best_metric_step,
                    "best_metric_epoch": final_early_stopping_state.best_metric_epoch,
                },
            }
            metrics_path.write_text(json.dumps(metrics_payload, indent=2, ensure_ascii=True), encoding="utf-8")
            if early_stop_completed.is_set():
                append_log(logs_path, "[training] Training stopped early after patience exhaustion.\n")
            _update_run(
                run_id,
                status="completed",
                finished_at=utc_now(),
                best_checkpoint_path=to_workspace_relative(best_checkpoint),
                error_message=None,
            )
        except Exception as exc:
            append_log(logs_path, f"[training-error] {exc}\n")
            _update_run(run_id, status="failed", finished_at=utc_now(), error_message=str(exc))
        finally:
            with _ACTIVE_RUNS_LOCK:
                _ACTIVE_RUNS.pop(run_id, None)
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

    threading.Thread(target=_runner, daemon=True).start()
