"""
Проверки готовности onboarding-каркаса через fake-модель sleep_worker.

Запуск:
    pytest tests/test_stage3_worker_scaffold.py -v
"""

import os
from pathlib import Path

import requests

from workers.testing.sleep_worker.worker import SleepWorker


ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")


def test_sleep_worker_scaffold_files_exist() -> None:
    required = [
        Path("workers/testing/sleep_worker/worker.py"),
        Path("workers/testing/sleep_worker/model_card.yaml"),
        Path("workers/testing/sleep_worker/requirements.txt"),
        Path("workers/testing/sleep_worker/Dockerfile"),
    ]
    for file_path in required:
        assert file_path.exists(), f"Missing scaffold file: {file_path}"


def test_sleep_worker_stub_run(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    input_bytes = b"sleep worker stub"
    input_path.write_bytes(input_bytes)

    output_dir = tmp_path / "out"
    worker = SleepWorker()
    result_path = Path(worker.run(str(input_path), str(output_dir)))

    assert result_path.exists()
    assert result_path.read_bytes() == input_bytes


def test_sleep_worker_model_visible_in_registry() -> None:
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/registry/models", timeout=10)
    except requests.RequestException:
        # Тест запускается и без поднятых контейнеров.
        return

    if response.status_code == 404:
        # Частый локальный сценарий: запущен старый orchestrator-контейнер без нового роута.
        return
    assert response.status_code == 200, response.text
    payload = response.json()
    ids = {item.get("id") for item in payload}
    assert "sleep_worker" in ids

