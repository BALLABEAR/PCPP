"""
Интеграционный тест Этапа 4 (DAG: fake segmentation -> snowflake completion).

Предусловие:
    docker compose up -d --build

Запуск:
    pytest tests/test_stage4_flow.py -v
"""

import os
import time
from pathlib import Path

import boto3
import pytest
import requests
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "pcpp_minio")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "pcpp_minio_secret")
MINIO_BUCKET_RESULTS = os.getenv("MINIO_BUCKET_RESULTS", "pcpp-results")


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def test_stage4_segmentation_completion_dag(tmp_path: Path) -> None:
    try:
        health_resp = requests.get(f"{ORCHESTRATOR_URL}/health", timeout=5)
        if health_resp.status_code != 200:
            pytest.skip("Orchestrator is not healthy; skip Stage 4 integration test.")
    except requests.RequestException:
        pytest.skip("Orchestrator is not running; skip Stage 4 integration test.")

    input_lines = [
        "0.0 0.0 0.0\n",
        "1.0 1.0 1.0\n",
        "2.0 2.0 2.0\n",
        "3.0 3.0 3.0\n",
        "4.0 4.0 4.0\n",
        "5.0 5.0 5.0\n",
    ]
    expected_lines = [
        "0.000000 0.000000 0.000000\n",
        "2.000000 2.000000 2.000000\n",
        "4.000000 4.000000 4.000000\n",
    ]

    test_file = tmp_path / "stage4_input.xyz"
    test_file.write_text("".join(input_lines), encoding="utf-8")

    with test_file.open("rb") as fh:
        upload_resp = requests.post(
            f"{ORCHESTRATOR_URL}/files/upload",
            files={"file": ("stage4_input.xyz", fh, "text/plain")},
            timeout=20,
        )
    assert upload_resp.status_code == 200, upload_resp.text
    uploaded = upload_resp.json()

    create_resp = requests.post(
        f"{ORCHESTRATOR_URL}/tasks",
        json={
            "input_bucket": uploaded["bucket"],
            "input_key": uploaded["key"],
            "flow_id": "stage4_segmentation_completion_flow",
            "flow_params": {"completion_mode": "passthrough"},
        },
        timeout=20,
    )
    assert create_resp.status_code == 200, create_resp.text
    task = create_resp.json()
    task_id = task["id"]

    deadline = time.time() + 120
    last_payload = task
    while time.time() < deadline:
        status_resp = requests.get(f"{ORCHESTRATOR_URL}/tasks/{task_id}", timeout=20)
        assert status_resp.status_code == 200, status_resp.text
        last_payload = status_resp.json()
        if last_payload["status"] in {"completed", "failed"}:
            break
        time.sleep(2)

    assert last_payload["status"] == "completed", last_payload
    assert last_payload["result_bucket"] == MINIO_BUCKET_RESULTS
    assert last_payload["result_key"], last_payload

    # Final output should match fake segmentation result because completion runs in passthrough mode.
    result = _s3_client().get_object(
        Bucket=last_payload["result_bucket"],
        Key=last_payload["result_key"],
    )
    output_text = result["Body"].read().decode("utf-8")
    assert output_text == "".join(expected_lines)

    intermediate_key = f"intermediate/{task_id}/segmented.xyz"
    _s3_client().head_object(Bucket=MINIO_BUCKET_RESULTS, Key=intermediate_key)
