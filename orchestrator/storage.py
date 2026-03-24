import os
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from fastapi import UploadFile


def get_s3_client(endpoint_url: str | None = None) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "pcpp_minio"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "pcpp_minio_secret"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def upload_input_file(file: UploadFile) -> tuple[str, str]:
    bucket = os.getenv("MINIO_BUCKET_FILES", "pcpp-files")
    ext = Path(file.filename or "").suffix
    key = f"uploads/{uuid4()}{ext}"

    file.file.seek(0)
    get_s3_client().upload_fileobj(file.file, bucket, key)
    return bucket, key


def generate_download_url(bucket: str, key: str, expires_seconds: int = 600) -> str:
    # Presigned URL must be signed for the same host the browser will call.
    public_endpoint = (os.getenv("MINIO_PUBLIC_ENDPOINT") or "http://localhost:9000").strip()
    return get_s3_client(endpoint_url=public_endpoint).generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )
