from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.models import SessionLocal
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.models.training_run import TrainingRun
from orchestrator.onboarding.runtime_ops import evaluate_runtime_readiness, manifest_hash_for_model_card
from orchestrator.training.logs import read_log
from orchestrator.training.metrics import (
    EarlyStoppingConfig,
    early_stopping_state_path_for_run,
    load_metric_events,
    metric_history_path_for_run,
    read_early_stopping_state,
    resolve_metric_views,
    summarize_metric_events,
)
from orchestrator.training.presets import (
    load_training_preset,
    list_training_presets,
    resolve_workspace_path,
    to_workspace_relative,
)
from orchestrator.training.runner import (
    build_run_artifacts,
    create_training_run_record,
    resolve_training_request,
    start_training_run,
)

router = APIRouter(prefix="/training", tags=["training"])


class TrainingRunRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    profile_id: str
    target_root: str
    training_data_root: str
    train_percent: int = 80
    val_percent: int = 10
    test_percent: int = 10
    mode: Literal["scratch", "finetune"] = "scratch"
    train_script_override: str = ""
    config_path_override: str = ""
    checkpoint_override: str = ""
    use_gpu: bool = True
    geometry_normalization: bool = True
    early_stopping_enabled: bool = False
    early_stopping_metric: str = ""
    early_stopping_mode: Literal["min", "max"] = "min"
    early_stopping_patience: int = 10
    early_stopping_min_delta: float = 0.0


class EarlyStoppingStateResponse(BaseModel):
    enabled: bool
    supported: bool
    monitor_metric: str | None
    mode: str | None
    patience: int | None
    min_delta: float | None
    triggered: bool = False
    stopped_early: bool = False
    stop_reason: str | None = None
    best_metric_value: float | None = None
    best_metric_step: int | None = None
    best_metric_epoch: int | None = None
    best_metric_tag: str | None = None
    observed_events: int = 0
    bad_epochs: int = 0
    last_metric_value: float | None = None


class TrainingMetricsResponse(BaseModel):
    run_id: str
    history_available: bool
    available_metric_tags: list[str]
    metric_series: dict[str, list[dict[str, Any]]]
    metrics_catalog: list[dict[str, Any]]
    resolved_metric_views: dict[str, dict[str, Any]]
    recommended_monitor_metric: str | None
    early_stopping_state: EarlyStoppingStateResponse


class TrainingRunResponse(BaseModel):
    run_id: str
    profile_id: str
    model_id: str
    task_type: str
    status: str
    mode: str
    target_root: str
    training_data_root: str
    train_percent: int
    val_percent: int
    test_percent: int
    split_counts: dict[str, int]
    sample_counts: dict[str, int]
    adapter_name: str | None
    adapter_dataset_root: str | None
    train_script: str
    config_path: str
    resolved_config_path: str
    run_dir: str
    metrics_path: str
    best_checkpoint_path: str | None
    best_checkpoint_pipeline_path: str | None
    geometry_normalization: bool
    metrics_history_available: bool
    available_metric_tags: list[str]
    metrics_catalog: list[dict[str, Any]]
    resolved_metric_views: dict[str, dict[str, Any]]
    recommended_monitor_metric: str | None
    early_stopping_state: EarlyStoppingStateResponse
    command: list[str]
    logs: str
    error_message: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None


class TrainingProfilesResponse(BaseModel):
    profiles: list[dict[str, Any]] = Field(default_factory=list)


def _normalize_workspace_relative_path(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.startswith("./") or value.startswith("/"):
        return value
    if value.startswith("training_runs/") or value.startswith("external_models/") or value.startswith("data/"):
        return f"./{value}"
    return value


def _to_pipeline_safe_path(raw: str | None) -> str | None:
    value = _normalize_workspace_relative_path(raw)
    if not value:
        return None
    if value.startswith("/app/"):
        return value
    if value.startswith("./"):
        return f"/app/{value[2:]}"
    return value


def _read_request_snapshot(run: TrainingRun) -> dict[str, Any]:
    run_dir = resolve_workspace_path(run.run_dir)
    snapshot_path = run_dir / "request_snapshot.json"
    if not snapshot_path.exists():
        return {}
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _build_early_stopping_config(snapshot: dict[str, Any]) -> EarlyStoppingConfig:
    payload = snapshot.get("early_stopping") or {}
    return EarlyStoppingConfig(
        enabled=bool(payload.get("enabled", False)),
        metric=str(payload.get("metric") or ""),
        mode=str(payload.get("mode") or "min"),
        patience=int(payload.get("patience", 10)),
        min_delta=float(payload.get("min_delta", 0.0)),
    )


def _read_metrics_state(
    run: TrainingRun,
    snapshot: dict[str, Any],
    preset: Any | None,
) -> tuple[bool, list[str], dict[str, dict[str, Any]], str | None, EarlyStoppingStateResponse]:
    run_dir = resolve_workspace_path(run.run_dir)
    history_path = metric_history_path_for_run(run_dir)
    early_stopping_path = early_stopping_state_path_for_run(run_dir)
    events = load_metric_events(history_path)
    available_tags, _ = summarize_metric_events(events)
    resolved_views, recommended_monitor_metric = resolve_metric_views(
        available_tags=available_tags,
        metric_catalog=list(getattr(preset, "metrics_catalog", []) or []),
        recommended_curves=dict(getattr(preset, "recommended_curves", {}) or {}),
    )
    early_state = read_early_stopping_state(early_stopping_path, _build_early_stopping_config(snapshot))
    return (
        bool(events),
        available_tags,
        resolved_views,
        recommended_monitor_metric,
        EarlyStoppingStateResponse(**early_state.__dict__),
    )


def _serialize_run(run: TrainingRun) -> TrainingRunResponse:
    logs_path = resolve_workspace_path(run.logs_path)
    snapshot = _read_request_snapshot(run)
    split_percentages = snapshot.get("split_percentages") or {}
    preset = load_training_preset(run.profile_id)
    metrics_history_available, available_metric_tags, resolved_metric_views, recommended_monitor_metric, early_stopping_state = _read_metrics_state(run, snapshot, preset)
    return TrainingRunResponse(
        run_id=run.id,
        profile_id=run.profile_id,
        model_id=run.model_id,
        task_type=run.task_type,
        status=run.status,
        mode=run.mode,
        target_root=str(snapshot.get("target_root") or run.dataset_root),
        training_data_root=str(snapshot.get("training_data_root") or ""),
        train_percent=int(split_percentages.get("train", 0)),
        val_percent=int(split_percentages.get("val", 0)),
        test_percent=int(split_percentages.get("test", 0)),
        split_counts={str(key): int(value) for key, value in (snapshot.get("split_counts") or {}).items()},
        sample_counts={str(key): int(value) for key, value in (snapshot.get("sample_counts") or {}).items()},
        adapter_name=snapshot.get("adapter_name"),
        adapter_dataset_root=snapshot.get("adapter_dataset_root"),
        train_script=run.train_script,
        config_path=run.config_path,
        resolved_config_path=run.resolved_config_path,
        run_dir=run.run_dir,
        metrics_path=run.metrics_path,
        best_checkpoint_path=_normalize_workspace_relative_path(run.best_checkpoint_path),
        best_checkpoint_pipeline_path=_to_pipeline_safe_path(run.best_checkpoint_path),
        geometry_normalization=bool(snapshot.get("geometry_normalization", True)),
        metrics_history_available=metrics_history_available,
        available_metric_tags=available_metric_tags,
        metrics_catalog=list(preset.metrics_catalog),
        resolved_metric_views=resolved_metric_views,
        recommended_monitor_metric=recommended_monitor_metric,
        early_stopping_state=early_stopping_state,
        command=json.loads(run.command_json),
        logs=read_log(logs_path),
        error_message=run.error_message,
        created_at=run.created_at.isoformat() if run.created_at else None,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
    )


@router.get("/profiles", response_model=TrainingProfilesResponse)
def list_profiles() -> TrainingProfilesResponse:
    presets = list_training_presets()
    db = SessionLocal()
    try:
        cards = {card.id: card for card in db.query(ModelCard).all()}
        statuses = {row.model_id: row for row in db.query(ModelRuntimeStatus).all()}
    finally:
        db.close()

    profiles: list[dict[str, Any]] = []
    for preset in presets:
        card = cards.get(preset.model_id)
        runtime = statuses.get(preset.model_id)
        ready, readiness_reason = evaluate_runtime_readiness(
            runtime,
            current_manifest_hash=manifest_hash_for_model_card(card.source_path) if card else None,
        )
        profiles.append(
            {
                "profile_id": preset.profile_id,
                "name": preset.name,
                "model_id": preset.model_id,
                "task_type": preset.task_type,
                "registered": card is not None,
                "ready": ready,
                "readiness_reason": readiness_reason,
                "default_train_script": to_workspace_relative(preset.default_train_script),
                "default_train_config": to_workspace_relative(preset.default_train_config),
                "default_finetune_checkpoint": (
                    to_workspace_relative(preset.default_finetune_checkpoint)
                    if preset.default_finetune_checkpoint
                    else None
                ),
                "dataset_kind": preset.dataset_kind,
                "dataset_fields": {
                    "target_root_label": "Путь к target",
                    "training_data_root_label": "Путь к обучающей выборке",
                    "geometry_normalization_label": "Нормализовать геометрию",
                },
                "dataset_structure_hint": (
                    "Ожидается структура вида Full_Clouds/<class>/<target>.ply и "
                    "Partial_Clouds/<class>/<target>/partial_XXX.ply."
                ),
                "geometry_normalization_hint": (
                    "Если включено, orchestrator нормализует partial и target для каждого объекта "
                    "по общему centroid/scale перед записью training artifacts."
                ),
                "adapter_managed_by": "orchestrator",
                "supported_modes": sorted(preset.modes.keys()),
                "metrics_catalog": list(preset.metrics_catalog),
                "recommended_curves": dict(preset.recommended_curves),
                "early_stopping_defaults": {
                    "enabled": bool(preset.early_stopping_defaults.get("enabled", False)),
                    "metric": str(preset.early_stopping_defaults.get("metric") or ""),
                    "mode": str(preset.early_stopping_defaults.get("mode") or "min"),
                    "patience": int(preset.early_stopping_defaults.get("patience", 10)),
                    "min_delta": float(preset.early_stopping_defaults.get("min_delta", 0.0)),
                },
            }
        )
    return TrainingProfilesResponse(profiles=profiles)


@router.post("/runs", response_model=TrainingRunResponse)
def start_run(payload: TrainingRunRequest) -> TrainingRunResponse:
    try:
        preset = load_training_preset(payload.profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    db = SessionLocal()
    try:
        card = db.get(ModelCard, preset.model_id)
        runtime = db.get(ModelRuntimeStatus, preset.model_id)
    finally:
        db.close()
    if card is None:
        raise HTTPException(status_code=409, detail=f"Model '{preset.model_id}' is not registered in the catalog.")
    ready, readiness_reason = evaluate_runtime_readiness(
        runtime,
        current_manifest_hash=manifest_hash_for_model_card(card.source_path),
    )
    if not ready:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Model '{preset.model_id}' is not runtime-ready "
                f"({readiness_reason or 'unknown_reason'}). Build and smoke-check it first."
            ),
        )

    try:
        resolved = resolve_training_request(
            preset=preset,
            mode=payload.mode,
            target_root_raw=payload.target_root,
            training_data_root_raw=payload.training_data_root,
            train_percent=payload.train_percent,
            val_percent=payload.val_percent,
            test_percent=payload.test_percent,
            train_script_raw=payload.train_script_override,
            config_path_raw=payload.config_path_override,
            checkpoint_path_raw=payload.checkpoint_override,
            use_gpu=payload.use_gpu,
            geometry_normalization=payload.geometry_normalization,
            early_stopping_enabled=payload.early_stopping_enabled,
            early_stopping_metric=payload.early_stopping_metric,
            early_stopping_mode=payload.early_stopping_mode,
            early_stopping_patience=payload.early_stopping_patience,
            early_stopping_min_delta=payload.early_stopping_min_delta,
        )
        run_id = uuid.uuid4().hex
        artifacts = build_run_artifacts(preset=preset, resolved=resolved, run_id=run_id)
        run = create_training_run_record(run_id=run_id, preset=preset, resolved=resolved, artifacts=artifacts)
        start_training_run(preset=preset, resolved=resolved, artifacts=artifacts, run_id=run.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db = SessionLocal()
    try:
        stored = db.get(TrainingRun, run.id)
        assert stored is not None
        return _serialize_run(stored)
    finally:
        db.close()


@router.get("/runs", response_model=list[TrainingRunResponse])
def list_runs() -> list[TrainingRunResponse]:
    db = SessionLocal()
    try:
        runs = db.query(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(50).all()
        return [_serialize_run(run) for run in runs]
    finally:
        db.close()


@router.get("/runs/{run_id}", response_model=TrainingRunResponse)
def get_run(run_id: str) -> TrainingRunResponse:
    db = SessionLocal()
    try:
        run = db.get(TrainingRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Training run not found")
        return _serialize_run(run)
    finally:
        db.close()


@router.get("/runs/{run_id}/metrics", response_model=TrainingMetricsResponse)
def get_run_metrics(run_id: str) -> TrainingMetricsResponse:
    db = SessionLocal()
    try:
        run = db.get(TrainingRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Training run not found")
    finally:
        db.close()

    snapshot = _read_request_snapshot(run)
    run_dir = resolve_workspace_path(run.run_dir)
    history_path = metric_history_path_for_run(run_dir)
    events = load_metric_events(history_path)
    available_metric_tags, metric_series = summarize_metric_events(events)
    early_state = read_early_stopping_state(
        early_stopping_state_path_for_run(run_dir),
        _build_early_stopping_config(snapshot),
    )
    preset = load_training_preset(run.profile_id)
    resolved_metric_views, recommended_monitor_metric = resolve_metric_views(
        available_tags=available_metric_tags,
        metric_catalog=list(preset.metrics_catalog),
        recommended_curves=dict(preset.recommended_curves),
    )
    return TrainingMetricsResponse(
        run_id=run.id,
        history_available=bool(events),
        available_metric_tags=available_metric_tags,
        metric_series=metric_series,
        metrics_catalog=list(preset.metrics_catalog),
        resolved_metric_views=resolved_metric_views,
        recommended_monitor_metric=recommended_monitor_metric,
        early_stopping_state=EarlyStoppingStateResponse(**early_state.__dict__),
    )
