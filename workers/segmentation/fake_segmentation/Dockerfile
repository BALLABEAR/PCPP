FROM python:3.11-slim

WORKDIR /app
COPY workers /app/workers
ENV PYTHONPATH=/app

CMD ["python", "-m", "workers.segmentation.fake_segmentation.worker", "--help"]
