from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


_LOCK = threading.Lock()


def _history_path() -> str:
    return str(os.getenv("PCPP_METRICS_HISTORY_PATH", "")).strip()


def _coerce_scalar_value(value: Any) -> float | None:
    if value is None:
        return None
    for attr in ("item",):
        if hasattr(value, attr):
            try:
                value = getattr(value, attr)()
                break
            except Exception:
                pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def append_scalar_event(
    source: str,
    tag: Any,
    scalar_value: Any,
    global_step: Any = None,
    walltime: Any = None,
) -> None:
    history_path = _history_path()
    if not history_path:
        return

    value = _coerce_scalar_value(scalar_value)
    if value is None:
        return

    try:
        step = int(global_step) if global_step is not None else None
    except (TypeError, ValueError):
        step = None
    try:
        wall_time = float(walltime) if walltime is not None else time.time()
    except (TypeError, ValueError):
        wall_time = time.time()

    payload = {
        "tag": str(tag),
        "value": value,
        "step": step,
        "wall_time": wall_time,
        "source": str(source or "unknown"),
    }
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    line = json.dumps(payload, ensure_ascii=True)
    with _LOCK:
        with open(history_path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def build_writer_class(real_cls: type[Any] | None, source: str) -> type[Any]:
    class CapturingSummaryWriter:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._delegate = None
            self.logdir = args[0] if args else kwargs.get("logdir") or kwargs.get("log_dir")
            if real_cls is not None:
                try:
                    self._delegate = real_cls(*args, **kwargs)
                    self.logdir = getattr(self._delegate, "logdir", None) or getattr(self._delegate, "log_dir", None) or self.logdir
                except Exception:
                    self._delegate = None

        def add_scalar(self, tag: Any, scalar_value: Any, global_step: Any = None, walltime: Any = None, *args: Any, **kwargs: Any) -> Any:
            append_scalar_event(source, tag, scalar_value, global_step, walltime)
            if self._delegate is not None and hasattr(self._delegate, "add_scalar"):
                return self._delegate.add_scalar(tag, scalar_value, global_step=global_step, walltime=walltime, *args, **kwargs)
            return None

        def flush(self) -> None:
            if self._delegate is not None and hasattr(self._delegate, "flush"):
                self._delegate.flush()

        def close(self) -> None:
            if self._delegate is not None and hasattr(self._delegate, "close"):
                self._delegate.close()

        def __getattr__(self, name: str) -> Any:
            if self._delegate is None:
                raise AttributeError(name)
            return getattr(self._delegate, name)

    return CapturingSummaryWriter


def patch_summary_writer_module(module: Any, source: str) -> Any:
    real_summary_writer = getattr(module, "SummaryWriter", None)
    real_file_writer = getattr(module, "FileWriter", real_summary_writer)
    module.SummaryWriter = build_writer_class(real_summary_writer, source)
    if real_file_writer is not None:
        module.FileWriter = build_writer_class(real_file_writer, source)
    return module
