import time
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from orchestrator.models import Base
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.pipelines.service import validate_pipeline_draft


ORCHESTRATOR_URL = "http://localhost:8000"


@pytest.fixture()
def db_session(tmp_path):
    db_file = tmp_path / "wizard_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_model(tmp_path: Path, db_session, model_id: str, *, generated: bool = True) -> Path:
    model_dir = tmp_path / "workers" / "completion" / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "__init__.py").write_text("", encoding="utf-8")
    (model_dir / "worker.py").write_text(
        "class GeneratedWorker:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (model_dir / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    card_path = model_dir / "model_card.yaml"
    card_path.write_text(
        f"id: {model_id}\n"
        "name: Test\n"
        "task_type: completion\n"
        "accepted_input_formats: [.xyz]\n"
        "produced_output_formats: [.ply]\n"
        "params:\n"
        "  weights_path:\n"
        "    type: path\n"
        "    aliases: [weights]\n"
        "  device:\n"
        "    type: str\n"
        "  use_gpu:\n"
        "    type: bool\n"
        "  batch_size:\n"
        "    type: int\n"
        "  threshold:\n"
        "    type: float\n"
        "  extra:\n"
        "    type: json\n",
        encoding="utf-8",
    )
    db_session.add(
        ModelCard(
            id=model_id,
            name=model_id,
            task_type="completion",
            description="Generated adapter scaffold" if generated else "Legacy model",
            source_path=str(card_path),
        )
    )
    db_session.commit()
    return model_dir


def test_validate_pipeline_draft_endpoint_shape() -> None:
    try:
        response = requests.post(
            f"{ORCHESTRATOR_URL}/pipelines/validate-draft",
            json={"name": "test", "steps": []},
            timeout=10,
        )
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip pipeline wizard API test.")

    if response.status_code in {404, 405}:
        pytest.skip("Old orchestrator instance is running without pipeline draft endpoints.")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "valid" in payload
    assert payload["valid"] is False
    assert "errors" in payload


def test_create_pipeline_draft_and_list_templates() -> None:
    pipeline_name = f"wizard-api-{int(time.time())}"
    create_payload = {
        "name": pipeline_name,
        "steps": [{"model_id": "sleep_worker", "params": {"weights_path": "/tmp/weights-a.pth", "device": "cpu"}}],
    }
    try:
        response = requests.post(
            f"{ORCHESTRATOR_URL}/pipelines/create-draft",
            json=create_payload,
            timeout=10,
        )
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip pipeline wizard API test.")

    if response.status_code in {404, 405}:
        pytest.skip("Old orchestrator instance is running without pipeline draft endpoints.")
    if response.status_code == 422:
        pytest.skip("Model registry is not initialized with expected test model.")

    assert response.status_code == 200, response.text
    templates_resp = requests.get(f"{ORCHESTRATOR_URL}/pipelines/templates", timeout=10)
    assert templates_resp.status_code == 200, templates_resp.text
    templates = templates_resp.json()
    created = next((item for item in templates if item.get("name") == pipeline_name and item.get("source") == "user"), None)
    assert created is not None
    step = created.get("flow_params", {}).get("pipeline_steps", [{}])[0]
    assert step.get("cli_args", {}).get("weights_path") == "/tmp/weights-a.pth"
    assert step.get("cli_args", {}).get("device") == "cpu"

    pipeline_id = created.get("pipeline_id")
    if pipeline_id:
        cleanup = requests.delete(f"{ORCHESTRATOR_URL}/pipelines/{pipeline_id}", timeout=10)
        assert cleanup.status_code in {200, 404}, cleanup.text


def test_delete_model_endpoint_exists() -> None:
    try:
        response = requests.delete(f"{ORCHESTRATOR_URL}/registry/models/definitely_missing_model", timeout=10)
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip model delete API test.")

    if response.status_code == 405:
        pytest.skip("Old orchestrator instance is running without model delete endpoint.")
    assert response.status_code == 404, response.text


def test_cleanup_stale_wizard_api_pipelines() -> None:
    try:
        templates_resp = requests.get(f"{ORCHESTRATOR_URL}/pipelines/templates", timeout=10)
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip cleanup test.")
    if templates_resp.status_code in {404, 405}:
        pytest.skip("Old orchestrator instance is running without pipeline template endpoints.")
    assert templates_resp.status_code == 200, templates_resp.text
    templates = templates_resp.json()
    for item in templates:
        name = str(item.get("name", ""))
        pipeline_id = item.get("pipeline_id")
        if item.get("source") == "user" and name.startswith("wizard-api-") and pipeline_id:
            resp = requests.delete(f"{ORCHESTRATOR_URL}/pipelines/{pipeline_id}", timeout=10)
            assert resp.status_code in {200, 404}, resp.text


def test_validate_pipeline_draft_blocks_unverified_generated_model(db_session, tmp_path: Path) -> None:
    _seed_model(tmp_path, db_session, "new_generated_model", generated=True)
    result = validate_pipeline_draft(
        db_session,
        name="draft-test",
        steps=[{"model_id": "new_generated_model", "params": {}}],
    )
    assert result["valid"] is False
    assert any("runtime-ready" in item for item in result["errors"])


def test_validate_pipeline_draft_accepts_ready_model_and_coerces_types(db_session, tmp_path: Path) -> None:
    _seed_model(tmp_path, db_session, "ready_model", generated=True)
    db_session.add(
        ModelRuntimeStatus(
            model_id="ready_model",
            build_ok=True,
            smoke_ok=True,
            last_image_tag="pcpp-completion-ready_model:gpu",
        )
    )
    db_session.commit()
    result = validate_pipeline_draft(
        db_session,
        name="draft-ready",
        steps=[
            {
                "model_id": "ready_model",
                "params": {
                    "weights": "/tmp/override.pth",
                    "use_gpu": "true",
                    "batch_size": "4",
                    "threshold": "0.5",
                    "extra": '{"a":1}',
                    "device": "cpu",
                },
            }
        ],
    )
    assert result["valid"] is True, result["errors"]
    cli_args = result["normalized_steps"][0]["cli_args"]
    assert cli_args["weights_path"] == "/tmp/override.pth"
    assert cli_args["use_gpu"] is True
    assert cli_args["batch_size"] == 4
    assert abs(cli_args["threshold"] - 0.5) < 0.0001
    assert cli_args["extra"] == {"a": 1}


def test_validate_pipeline_draft_rejects_unknown_param_with_schema(db_session, tmp_path: Path) -> None:
    _seed_model(tmp_path, db_session, "strict_model", generated=True)
    db_session.add(
        ModelRuntimeStatus(
            model_id="strict_model",
            build_ok=True,
            smoke_ok=True,
            last_image_tag="pcpp-completion-strict_model:gpu",
        )
    )
    db_session.commit()
    result = validate_pipeline_draft(
        db_session,
        name="draft-strict",
        steps=[{"model_id": "strict_model", "params": {"unknown_flag": "1"}}],
    )
    assert result["valid"] is False
    assert any("not supported by this model" in item for item in result["errors"])
