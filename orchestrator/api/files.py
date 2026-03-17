import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from orchestrator.storage import generate_download_url, upload_input_file

router = APIRouter(prefix="/files", tags=["files"])
logger = logging.getLogger("orchestrator.files")


@router.post("/upload")
def upload_file(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    bucket, key = upload_input_file(file)
    logger.info("Uploaded file %s to %s/%s", file.filename, bucket, key)
    return {"bucket": bucket, "key": key, "filename": file.filename}


@router.get("/download")
def get_download_url(
    bucket: str = Query(..., description="S3 bucket name"),
    key: str = Query(..., description="S3 object key"),
    expires_seconds: int = Query(600, ge=60, le=3600),
) -> dict[str, str]:
    try:
        url = generate_download_url(bucket=bucket, key=key, expires_seconds=expires_seconds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot generate download URL: {exc}") from exc
    return {"bucket": bucket, "key": key, "url": url}

