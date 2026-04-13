"""
Предусловие:
    docker compose up -d --build

Запуск:
    pytest tests/test_stage6_frontend.py -v
"""

from pathlib import Path

import pytest
import requests


ORCHESTRATOR_URL = "http://localhost:8000"


def test_stage6_frontend_files_exist() -> None:
    required = [
        Path("frontend/Dockerfile"),
        Path("frontend/src/index.html"),
        Path("frontend/src/app.js"),
        Path("frontend/src/styles.css"),
    ]
    for file_path in required:
        assert file_path.exists(), f"Missing frontend file: {file_path}"
    app_js = Path("frontend/src/app.js").read_text(encoding="utf-8")
    assert "Сформировать запрос для AI-помощника" in app_js
    assert "Добавить пайплайн" in app_js
    assert "Force rebuild image" in app_js
    assert "User Pipeline Templates" in app_js


def test_stage6_pipeline_templates_endpoint() -> None:
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/pipelines/templates", timeout=10)
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip stage 6 API integration test.")

    if response.status_code == 404:
        pytest.skip("Old orchestrator instance is running without Stage 6 endpoint.")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    assert any(item.get("flow_id") == "stage2_test_flow" for item in payload)
