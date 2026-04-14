import threading
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


RUNS_LOCK = threading.Lock()
RUNS: dict[str, dict[str, Any]] = {}
