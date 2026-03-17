"""
Интеграционные тесты Этапа 2 (FastAPI + Prefect + тестовый воркер).

Предусловие:
    docker compose up -d --build

Запуск:
    pytest tests/test_stage2_flow.py -v
"""

import os
import time
from pathlib import Path
from uuid import uuid4

import boto3
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


def test_stage2_end_to_end(tmp_path: Path):
    test_content = f"pcpp-stage2-{uuid4()}".encode("utf-8")
    test_file = tmp_path / "input.txt"
    test_file.write_bytes(test_content)

    with test_file.open("rb") as fh:
        upload_resp = requests.post(
            f"{ORCHESTRATOR_URL}/files/upload",
            files={"file": ("input.txt", fh, "text/plain")},
            timeout=20,
        )
    assert upload_resp.status_code == 200, upload_resp.text
    uploaded = upload_resp.json()
    assert "bucket" in uploaded and "key" in uploaded

    create_resp = requests.post(
        f"{ORCHESTRATOR_URL}/tasks",
        json={"input_bucket": uploaded["bucket"], "input_key": uploaded["key"]},
        timeout=20,
    )
    assert create_resp.status_code == 200, create_resp.text
    task = create_resp.json()
    task_id = task["id"]

    deadline = time.time() + 90
    last_payload = task
    while time.time() < deadline:
        status_resp = requests.get(f"{ORCHESTRATOR_URL}/tasks/{task_id}", timeout=20)
        assert status_resp.status_code == 200, status_resp.text
        last_payload = status_resp.json()
        if last_payload["status"] in {"completed", "failed"}:
            break
        time.sleep(2)

    assert last_payload["status"] == "completed", last_payload
    assert last_payload["result_key"], last_payload
    assert last_payload["result_bucket"] == MINIO_BUCKET_RESULTS

    result = _s3_client().get_object(
        Bucket=last_payload["result_bucket"],
        Key=last_payload["result_key"],
    )
    downloaded = result["Body"].read()
    assert downloaded == test_content
