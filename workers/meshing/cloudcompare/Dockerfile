FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    cloudcompare \
    && rm -rf /var/lib/apt/lists/*

COPY workers/meshing/cloudcompare/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /workspace
ENV PYTHONPATH=/workspace
