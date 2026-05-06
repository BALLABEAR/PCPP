from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


METRICS_HISTORY_FILENAME = "metrics_history.jsonl"
EARLY_STOPPING_STATE_FILENAME = "early_stopping_state.json"


@dataclass(frozen=True)
class MetricEvent:
    tag: str
    value: float
    step: int | None
    wall_time: float | None
    source: str


@dataclass(frozen=True)
class EarlyStoppingConfig:
    enabled: bool = False
    metric: str = ""
    mode: str = "min"
    patience: int = 10
    min_delta: float = 0.0


@dataclass
class EarlyStoppingState:
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


@dataclass(frozen=True)
class ResolvedMetricView:
    key: str
    label: str
    role: str
    direction: str
    resolved_tag: str | None
    source: str


def metric_history_path_for_run(run_dir: Path) -> Path:
    return run_dir / METRICS_HISTORY_FILENAME


def early_stopping_state_path_for_run(run_dir: Path) -> Path:
    return run_dir / EARLY_STOPPING_STATE_FILENAME


def default_early_stopping_state(config: EarlyStoppingConfig) -> EarlyStoppingState:
    metric = config.metric.strip() or None
    enabled = bool(config.enabled)
    supported = enabled and metric is not None
    return EarlyStoppingState(
        enabled=enabled,
        supported=supported,
        monitor_metric=metric,
        mode=config.mode if enabled else None,
        patience=config.patience if enabled else None,
        min_delta=config.min_delta if enabled else None,
        stop_reason=None if enabled else "disabled",
    )


def parse_metric_event(raw: dict[str, Any]) -> MetricEvent | None:
    tag = str(raw.get("tag") or "").strip()
    source = str(raw.get("source") or "").strip() or "unknown"
    if not tag:
        return None

    try:
        value = float(raw["value"])
    except (KeyError, TypeError, ValueError):
        return None

    step_value = raw.get("step")
    wall_time_value = raw.get("wall_time")

    try:
        step = int(step_value) if step_value is not None else None
    except (TypeError, ValueError):
        step = None
    try:
        wall_time = float(wall_time_value) if wall_time_value is not None else None
    except (TypeError, ValueError):
        wall_time = None

    return MetricEvent(
        tag=tag,
        value=value,
        step=step,
        wall_time=wall_time,
        source=source,
    )


def load_metric_events(history_path: Path) -> list[MetricEvent]:
    if not history_path.exists():
        return []

    events: list[MetricEvent] = []
    try:
        with history_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                event = parse_metric_event(payload if isinstance(payload, dict) else {})
                if event is not None:
                    events.append(event)
    except OSError:
        return []
    return events


def summarize_metric_events(events: list[MetricEvent]) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    tags: list[str] = []
    series: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.tag not in series:
            tags.append(event.tag)
            series[event.tag] = []
        series[event.tag].append(
            {
                "value": event.value,
                "step": event.step,
                "wall_time": event.wall_time,
                "source": event.source,
            }
        )
    return tags, series


def resolve_metric_views(
    *,
    available_tags: list[str],
    metric_catalog: list[dict[str, Any]],
    recommended_curves: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], str | None]:
    safe_tags = [str(tag).strip() for tag in available_tags if str(tag).strip()]
    resolved: dict[str, dict[str, Any]] = {}
    recommended_monitor_metric: str | None = None

    for item in metric_catalog:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        label = str(item.get("label") or key).strip()
        role = str(item.get("role") or "aux").strip()
        direction = str(item.get("direction") or "min").strip()
        patterns = [str(value).strip().lower() for value in (item.get("preferred_tag_patterns") or []) if str(value).strip()]
        exact_tag = str(item.get("resolved_tag") or "").strip()

        resolved_tag = exact_tag if exact_tag in safe_tags else None
        if resolved_tag is None and patterns:
            scored: list[tuple[int, str]] = []
            for tag in safe_tags:
                tag_lower = tag.lower()
                matches = sum(1 for pattern in patterns if pattern in tag_lower)
                if matches > 0:
                    scored.append((matches, tag))
            if scored:
                scored.sort(key=lambda item: (-item[0], item[1]))
                resolved_tag = scored[0][1]

        resolved[key] = {
            "key": key,
            "label": label,
            "role": role,
            "direction": direction,
            "resolved_tag": resolved_tag,
            "source": "preset" if resolved_tag else "unresolved",
        }
        if recommended_monitor_metric is None and role in {"val", "test"} and resolved_tag:
            recommended_monitor_metric = resolved_tag

    for slot, curve_key in (recommended_curves or {}).items():
        if curve_key in resolved:
            resolved[slot] = dict(resolved[curve_key], key=slot)

    return resolved, recommended_monitor_metric


def write_early_stopping_state(path: Path, state: EarlyStoppingState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=True), encoding="utf-8")


def read_early_stopping_state(path: Path, config: EarlyStoppingConfig) -> EarlyStoppingState:
    fallback = default_early_stopping_state(config)
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

    if not isinstance(payload, dict):
        return fallback

    try:
        return EarlyStoppingState(
            enabled=bool(payload.get("enabled", fallback.enabled)),
            supported=bool(payload.get("supported", fallback.supported)),
            monitor_metric=payload.get("monitor_metric", fallback.monitor_metric),
            mode=payload.get("mode", fallback.mode),
            patience=int(payload["patience"]) if payload.get("patience") is not None else fallback.patience,
            min_delta=float(payload["min_delta"]) if payload.get("min_delta") is not None else fallback.min_delta,
            triggered=bool(payload.get("triggered", False)),
            stopped_early=bool(payload.get("stopped_early", False)),
            stop_reason=payload.get("stop_reason"),
            best_metric_value=(
                float(payload["best_metric_value"]) if payload.get("best_metric_value") is not None else None
            ),
            best_metric_step=int(payload["best_metric_step"]) if payload.get("best_metric_step") is not None else None,
            best_metric_epoch=(
                int(payload["best_metric_epoch"]) if payload.get("best_metric_epoch") is not None else None
            ),
            best_metric_tag=payload.get("best_metric_tag"),
            observed_events=int(payload.get("observed_events", 0)),
            bad_epochs=int(payload.get("bad_epochs", 0)),
            last_metric_value=float(payload["last_metric_value"]) if payload.get("last_metric_value") is not None else None,
        )
    except (TypeError, ValueError):
        return fallback


def evaluate_early_stopping(
    config: EarlyStoppingConfig,
    history_path: Path,
    *,
    previous_state: EarlyStoppingState | None = None,
) -> EarlyStoppingState:
    state = previous_state or default_early_stopping_state(config)
    if not config.enabled:
        return default_early_stopping_state(config)

    monitor_metric = config.metric.strip()
    if not monitor_metric:
        unsupported = default_early_stopping_state(config)
        unsupported.supported = False
        unsupported.stop_reason = "monitor metric is empty"
        return unsupported

    events = [event for event in load_metric_events(history_path) if event.tag == monitor_metric]
    next_state = default_early_stopping_state(config)
    next_state.supported = True
    next_state.stop_reason = None
    next_state.observed_events = len(events)
    next_state.best_metric_tag = monitor_metric
    if not events:
        return next_state

    best_value: float | None = None
    best_step: int | None = None
    best_epoch: int | None = None
    bad_epochs = 0
    last_value: float | None = None

    for event in events:
        last_value = event.value
        if best_value is None:
            improved = True
        elif config.mode == "max":
            improved = event.value > (best_value + config.min_delta)
        else:
            improved = event.value < (best_value - config.min_delta)

        if improved:
            best_value = event.value
            best_step = event.step
            best_epoch = event.step
            bad_epochs = 0
        else:
            bad_epochs += 1

    next_state.best_metric_value = best_value
    next_state.best_metric_step = best_step
    next_state.best_metric_epoch = best_epoch
    next_state.bad_epochs = bad_epochs
    next_state.last_metric_value = last_value

    if config.patience >= 0 and bad_epochs >= config.patience:
        next_state.triggered = True
        next_state.stopped_early = True
        next_state.stop_reason = (
            f"No improvement in '{monitor_metric}' for {bad_epochs} validation events "
            f"(patience={config.patience}, mode={config.mode})."
        )
    return next_state
