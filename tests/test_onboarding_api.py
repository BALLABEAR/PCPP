from pathlib import Path

import pytest
import requests


ORCHESTRATOR_URL = "http://localhost:8000"


def test_onboarding_validate_rejects_bad_model_id() -> None:
    try:
        response = requests.post(
            f"{ORCHESTRATOR_URL}/onboarding/models/validate",
            json={
                "model_id": "BadModel",
                "task_type": "completion",
                "repo_path": "./external_models/PoinTr",
                "weights_path": "./external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth",
                "config_path": "./external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml",
                "input_data_kind": "point_cloud",
                "output_data_kind": "point_cloud",
            },
            timeout=10,
        )
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip onboarding API integration test.")

    if response.status_code == 404:
        pytest.skip("Old orchestrator instance is running without onboarding endpoints.")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    assert any("lower_snake_case" in item for item in payload["errors"])


def test_onboarding_validate_accepts_existing_local_paths() -> None:
    repo = Path("external_models/PoinTr")
    weights = Path("external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth")
    config = Path("external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml")
    if not (repo.exists() and weights.exists() and config.exists()):
        pytest.skip("PoinTr assets are not present in this workspace.")

    response = requests.post(
        f"{ORCHESTRATOR_URL}/onboarding/models/validate",
        json={
            "model_id": "poin_tr",
            "task_type": "completion",
            "repo_path": "./external_models/PoinTr",
            "weights_path": "./external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth",
            "config_path": "./external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml",
            "input_data_kind": "point_cloud",
            "output_data_kind": "point_cloud",
        },
        timeout=10,
    )
    if response.status_code == 404:
        pytest.skip("Old orchestrator instance is running without onboarding endpoints.")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is True


def test_onboarding_registry_check_endpoint_shape() -> None:
    try:
        response = requests.post(
            f"{ORCHESTRATOR_URL}/onboarding/models/registry-check",
            json={"model_id": "non_existing_model_for_test"},
            timeout=10,
        )
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip onboarding API integration test.")
    if response.status_code == 404:
        pytest.skip("Old orchestrator instance is running without onboarding endpoints.")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "registered" in payload
    assert payload["model_id"] == "non_existing_model_for_test"

