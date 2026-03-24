FROM python:3.11-slim

WORKDIR /app

COPY orchestrator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY orchestrator /app/orchestrator
COPY flows /app/flows
COPY workers /app/workers
COPY external_models /app/external_models

ENV PYTHONPATH=/app

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
