FROM python:3.11-slim

WORKDIR /app

COPY workers/completion/snowflake_net/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY workers /app/workers

ENV PYTHONPATH=/app

CMD ["python", "-m", "workers.completion.snowflake_net.worker", "--help"]
