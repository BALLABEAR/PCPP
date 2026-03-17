import os
import tempfile
import time
from pathlib import Path

import boto3
from botocore.config import Config
from prefect import flow, get_run_logger, task


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "pcpp_minio"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "pcpp_minio_secret"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


@task(name="test_worker_step")
def run_test_worker(task_id: str, input_bucket: str, input_key: str, result_bucket: str) -> str:
    logger = get_run_logger()
    s3 = _s3_client()

    suffix = Path(input_key).suffix
    output_key = f"results/{task_id}/processed{suffix or '.bin'}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_in = Path(tmp_dir) / f"input{suffix or '.bin'}"
        local_out = Path(tmp_dir) / f"output{suffix or '.bin'}"

        logger.info("Downloading input s3://%s/%s", input_bucket, input_key)
        s3.download_file(input_bucket, input_key, str(local_in))

        logger.info("Simulating worker processing (5 seconds)")
        time.sleep(5)

        local_out.write_bytes(local_in.read_bytes())

        logger.info("Uploading result s3://%s/%s", result_bucket, output_key)
        s3.upload_file(str(local_out), result_bucket, output_key)

    return output_key


@flow(name="stage2-test-flow", log_prints=True)
def stage2_test_flow(task_id: str, input_bucket: str, input_key: str, result_bucket: str) -> str:
    logger = get_run_logger()
    logger.info("Stage2 flow started for task %s", task_id)
    result_key = run_test_worker(task_id, input_bucket, input_key, result_bucket)
    logger.info("Stage2 flow completed for task %s", task_id)
    return result_key
