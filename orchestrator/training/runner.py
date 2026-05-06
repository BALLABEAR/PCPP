from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from orchestrator.models import SessionLocal
from orchestrator.models.training_run import TrainingRun
from orchestrator.training.checkpoints import find_best_checkpoint
from orchestrator.training.dataset_adapters import (
    SplitPercentages,
    get_training_adapter,
)
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
class ResolvedTrainingRequest:
    mode: str
    target_root: Path
    training_data_root: Path
    split_percentages: SplitPercentages
    dataset: Any
    train_script: Path
    config_path: Path
    checkpoint_path: Path | None
    use_gpu: bool
    geometry_normalization: bool
    early_stopping: EarlyStoppingConfig


def resolve_training_request(
    *,
    preset: TrainingPreset,
    mode: str,
    target_root_raw: str,
    training_data_root_raw: str,
    train_percent: int,
    val_percent: int,
    test_percent: int,
    train_script_raw: str,
    config_path_raw: str,
    checkpoint_path_raw: str,
    use_gpu: bool,
    geometry_normalization: bool,
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

    root = workspace_root()
    target_root = resolve_workspace_path(target_root_raw)
    training_data_root = resolve_workspace_path(training_data_root_raw)
    ensure_within(target_root, root, label="Target path")
    ensure_within(training_data_root, root, label="Training data path")
    split_percentages = SplitPercentages(
        train=train_percent,
        val=val_percent,
        test=test_percent,
    )
    adapter = get_training_adapter(preset.adapter_id)
    dataset = adapter.resolve_dataset(
        target_root=target_root,
        training_data_root=training_data_root,
        split_percentages=split_percentages,
    )

    working_dir = preset.working_dir
    train_script = (
        resolve_workspace_path(train_script_raw, base_dir=working_dir)
        if str(train_script_raw or "").strip()
        else preset.default_train_script
    )
    config_path = (
        resolve_workspace_path(config_path_raw, base_dir=working_dir)
        if str(config_path_raw or "").strip()
        else preset.default_train_config
    )
    ensure_within(train_script, workspace_root(), label="Train script")
    ensure_within(config_path, workspace_root(), label="Config path")
    if not train_script.exists():
        raise ValueError(f"Train script not found: {train_script}")
    if not config_path.exists():
        raise ValueError(f"Config path not found: {config_path}")

    checkpoint_path: Path | None = None
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
        target_root=target_root,
        training_data_root=training_data_root,
        split_percentages=split_percentages,
        dataset=dataset,
        train_script=train_script,
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        use_gpu=use_gpu,
        geometry_normalization=geometry_normalization,
        early_stopping=EarlyStoppingConfig(
            enabled=bool(early_stopping_enabled),
            metric=early_stopping_metric,
            mode=early_stopping_mode,
            patience=int(early_stopping_patience),
            min_delta=float(early_stopping_min_delta),
        ),
    )


def build_run_artifacts(
    *,
    preset: TrainingPreset,
    resolved: ResolvedTrainingRequest,
    run_id: str,
) -> dict[str, Any]:
    run_dir = training_runs_root() / preset.model_id / run_id
    artifacts_dir = run_dir / "artifacts"
    logs_path = run_dir / "run.log"
    request_path = run_dir / "request_snapshot.json"
    resolved_config_path = run_dir / "resolved_config.yaml"
    metrics_path = run_dir / "metrics.json"
    metrics_history_path = metric_history_path_for_run(run_dir)
    early_stopping_state_path = early_stopping_state_path_for_run(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    adapter = get_training_adapter(preset.adapter_id)
    dataset_artifacts = adapter.prepare_artifacts(
        preset=preset,
        dataset=resolved.dataset,
        run_dir=run_dir,
        geometry_normalization=resolved.geometry_normalization,
    )

    payload = yaml.safe_load(resolved.config_path.read_text(encoding="utf-8")) or {}
    payload = adapter.patch_config(
        payload=payload,
        preset=preset,
        dataset_artifacts=dataset_artifacts,
        checkpoint_path=resolved.checkpoint_path,
        artifacts_dir=artifacts_dir,
        use_gpu=resolved.use_gpu,
        mode_settings=dict(preset.modes.get(resolved.mode, {})),
    )

    resolved_config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    snapshot = {
        "profile_id": preset.profile_id,
        "model_id": preset.model_id,
        "mode": resolved.mode,
        "target_root": to_workspace_relative(resolved.target_root),
        "training_data_root": to_workspace_relative(resolved.training_data_root),
        "split_percentages": {
            "train": resolved.split_percentages.train,
            "val": resolved.split_percentages.val,
            "test": resolved.split_percentages.test,
        },
        "split_counts": dataset_artifacts.split_counts,
        "sample_counts": dataset_artifacts.sample_counts,
        "adapter_name": dataset_artifacts.adapter_name,
        "adapter_dataset_root": to_workspace_relative(dataset_artifacts.dataset_root),
        "adapter_category_file_path": to_workspace_relative(dataset_artifacts.category_file_path),
        "train_script": to_workspace_relative(resolved.train_script),
        "config_path": to_workspace_relative(resolved.config_path),
        "resolved_config_path": to_workspace_relative(resolved_config_path),
        "checkpoint_path": to_workspace_relative(resolved.checkpoint_path) if resolved.checkpoint_path else "",
        "use_gpu": resolved.use_gpu,
        "geometry_normalization": resolved.geometry_normalization,
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

    script_container_path = Path(to_container_path(resolved.train_script))
    working_dir_container_path = Path(to_container_path(preset.working_dir))
    try:
        script_arg = str(script_container_path.relative_to(working_dir_container_path))
    except ValueError:
        script_arg = str(script_container_path)

    command = [
        "python",
        script_arg,
        "--config",
        to_container_path(resolved_config_path),
    ]
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
        "dataset_artifacts": dataset_artifacts,
    }


def create_training_run_record(
    *,
    run_id: str,
    preset: TrainingPreset,
    resolved: ResolvedTrainingRequest,
    artifacts: dict[str, Any],
) -> TrainingRun:
    run = TrainingRun(
        id=run_id,
        profile_id=preset.profile_id,
        model_id=preset.model_id,
        task_type=preset.task_type,
        status="pending",
        mode=resolved.mode,
        dataset_root=to_workspace_relative(resolved.target_root),
        train_script=to_workspace_relative(resolved.train_script),
        config_path=to_workspace_relative(resolved.config_path),
        resolved_config_path=to_workspace_relative(artifacts["resolved_config_path"]),
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


def start_training_run(
    *,
    preset: TrainingPreset,
    resolved: ResolvedTrainingRequest,
    artifacts: dict[str, Any],
    run_id: str,
) -> None:
    logs_path = artifacts["logs_path"]
    command = artifacts["command"]
    run_dir = artifacts["run_dir"]
    metrics_path = artifacts["metrics_path"]
    metrics_history_path = artifacts["metrics_history_path"]
    early_stopping_state_path = artifacts["early_stopping_state_path"]

    def _runner() -> None:
        _update_run(run_id, status="running", started_at=utc_now())
        append_log(logs_path, f"[training] Starting run {run_id}\n")
        append_log(logs_path, f"[training] image={preset.image_tag}\n")
        append_log(logs_path, f"[training] command={' '.join(command)}\n")
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
        try:
            import docker
            from docker.errors import DockerException
            from docker.types import DeviceRequest

            client = docker.from_env()
            env = {
                "PYTHONUNBUFFERED": "1",
                # Some third-party training images bundle tensorboardX with
                # protobuf codegen that is incompatible with the default C++
                # implementation shipped in newer protobuf wheels.
                "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python",
                # Prepend orchestrator-managed import shims without touching
                # code in external_models.
                "PYTHONPATH": "/app/orchestrator/training/runtime_shims:/app",
                "PCPP_METRICS_HISTORY_PATH": to_container_path(metrics_history_path),
            }
            device_requests = None
            if resolved.use_gpu:
                env["NVIDIA_VISIBLE_DEVICES"] = "all"
                env["NVIDIA_DRIVER_CAPABILITIES"] = "compute,utility"
                device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

            container = client.containers.run(
                preset.image_tag,
                command=command,
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

            def _monitor_early_stopping() -> None:
                if not resolved.early_stopping.enabled:
                    return
                while not monitor_stop.is_set():
                    state = evaluate_early_stopping(
                        resolved.early_stopping,
                        metrics_history_path,
                    )
                    write_early_stopping_state(early_stopping_state_path, state)
                    if state.triggered and not early_stop_requested.is_set():
                        early_stop_requested.set()
                        append_log(
                            logs_path,
                            f"[training] Early stopping triggered: {state.stop_reason or 'threshold reached'}\n",
                        )
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
            monitor_stop.set()
            final_early_stopping_state = evaluate_early_stopping(
                resolved.early_stopping,
                metrics_history_path,
            )
            if early_stop_requested.is_set():
                final_early_stopping_state.triggered = True
                final_early_stopping_state.stopped_early = True
                final_early_stopping_state.stop_reason = (
                    final_early_stopping_state.stop_reason or "Training stopped by orchestrator early stopping."
                )
                early_stop_completed.set()
            write_early_stopping_state(early_stopping_state_path, final_early_stopping_state)

            if exit_code != 0 and not early_stop_completed.is_set():
                message = f"Training container exited with code {exit_code}"
                append_log(logs_path, f"[training-error] {message}\n")
                _update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    error_message=message,
                )
                return

            best_checkpoint = find_best_checkpoint(run_dir, preset.checkpoint_priority)
            if best_checkpoint is None:
                message = "Training completed, but no checkpoint matching preset rules was found."
                if resolved.mode == "finetune" and resolved.checkpoint_path is not None:
                    message += (
                        " Finetune likely resumed from a checkpoint whose stored epoch_index is already "
                        "greater than or equal to the configured train.epochs, so no new epochs were run."
                    )
                append_log(logs_path, f"[training-error] {message}\n")
                _update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    error_message=message,
                )
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
            _update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=str(exc),
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

    threading.Thread(target=_runner, daemon=True).start()
