import logging
import os
import threading
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

import docker
from sqlalchemy.orm import Session

from orchestrator.models.task import Task

logger = logging.getLogger(__name__)
_TASK_LOGS_LOCK = threading.Lock()
_TASK_LOGS: dict[str, str] = {}


def append_task_log(task_id: str, message: str) -> None:
    with _TASK_LOGS_LOCK:
        _TASK_LOGS[task_id] = _TASK_LOGS.get(task_id, "") + message.rstrip() + "\n"


def get_task_logs(task_id: str) -> str:
    with _TASK_LOGS_LOCK:
        return _TASK_LOGS.get(task_id, "")


def _debug_log(hypothesis_id: str, message: str, data: dict | None = None, run_id: str = "prefect-thread") -> None:
    # Legacy debug sink removed: keep calls as no-op.
    return None


class PrefectClient:
    """Единая точка связи FastAPI c Prefect Flow."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def trigger_flow(
        self,
        task_id: str,
        input_bucket: str,
        input_key: str,
        flow_id: str = "pipeline_flow",
        flow_params: dict | None = None,
    ) -> str:
        flow_run_name = f"{flow_id}-task-{task_id}"
        worker_thread = threading.Thread(
            target=self._run_flow_thread,
            kwargs={
                "task_id": task_id,
                "flow_run_name": flow_run_name,
                "input_bucket": input_bucket,
                "input_key": input_key,
                "flow_id": flow_id,
                "flow_params": flow_params or {},
                "result_bucket": os.getenv("MINIO_BUCKET_RESULTS", "pcpp-results"),
            },
            daemon=True,
        )
        worker_thread.start()
        append_task_log(task_id, f"[task] Triggered flow '{flow_id}' as '{flow_run_name}'")
        return flow_run_name

    def cancel_task(self, task_id: str) -> None:
        self._update_task(task_id, "cancelled", None, None, "Cancelled by user request")
        # Stop worker containers created by this task.
        try:
            client = docker.from_env()
            containers = client.containers.list(
                all=True,
                filters={"label": [f"pcpp.task_id={task_id}"]},
            )
            for container in containers:
                try:
                    container.remove(force=True)
                except Exception:
                    logger.exception("Failed to remove worker container %s for task %s", container.name, task_id)
        except Exception:
            logger.exception("Failed to cancel docker workers for task %s", task_id)

    def _run_flow_thread(
        self,
        task_id: str,
        flow_run_name: str,
        input_bucket: str,
        input_key: str,
        flow_id: str,
        flow_params: dict,
        result_bucket: str,
    ) -> None:
        try:
            from flows.flows_registry import get_registered_flows

            registered = get_registered_flows()
            flow_callable = registered.get(flow_id)
            if flow_callable is None:
                raise ValueError(f"Unknown flow_id: {flow_id}")

            append_task_log(task_id, f"[flow] Starting flow thread for {flow_id}")
            # #region agent log
            _debug_log(
                "H4",
                "flow thread starting",
                {
                    "task_id": task_id,
                    "flow_id": flow_id,
                    "flow_params_keys": sorted(list((flow_params or {}).keys())),
                    "pipeline_steps_len": len((flow_params or {}).get("pipeline_steps", []) or []),
                },
                run_id=task_id,
            )
            # #endregion
            self._update_task(task_id, "running", None, None)
            append_task_log(task_id, "[flow] Status -> running")
            result_key = flow_callable.with_options(name=flow_run_name)(
                task_id=task_id,
                input_bucket=input_bucket,
                input_key=input_key,
                result_bucket=result_bucket,
                **flow_params,
            )
            self._update_task(task_id, "completed", result_bucket, result_key)
            append_task_log(task_id, f"[flow] Completed. result_key={result_key}")
        except Exception as exc:
            logger.exception("Flow execution failed for task %s", task_id)
            append_task_log(task_id, f"[flow] Failed: {exc}")
            # #region agent log
            _debug_log(
                "H5",
                "flow thread exception",
                {
                    "task_id": task_id,
                    "flow_id": flow_id,
                    "error": str(exc),
                    "traceback": traceback.format_exc()[-4000:],
                },
                run_id=task_id,
            )
            # #endregion
            self._update_task(task_id, "failed", None, None, str(exc))

    def _update_task(
        self,
        task_id: str,
        status: str,
        result_bucket: str | None,
        result_key: str | None,
        error_message: str | None = None,
    ) -> None:
        db: Session = self.session_factory()
        try:
            task = db.get(Task, task_id)
            if not task:
                return
            if task.status == "cancelled" and status in {"running", "completed", "failed"}:
                return
            task.status = status
            task.result_bucket = result_bucket
            task.result_key = result_key
            task.error_message = error_message
            db.commit()
            if error_message:
                append_task_log(task_id, f"[task] error_message={error_message}")
            # #region agent log
            _debug_log(
                "H6",
                "task status updated",
                {"task_id": task_id, "status": status, "has_error": bool(error_message), "error": error_message},
                run_id=task_id,
            )
            # #endregion
        finally:
            db.close()
