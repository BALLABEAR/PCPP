FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel pyyaml

COPY workers/base/runtime /app/workers/base/runtime
COPY workers/meshing/shape_as_points/runtime.manifest.yaml /app/runtime.manifest.yaml
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase system
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase python

COPY workers /app/workers
COPY external_models /app/external_models
ENV PYTHONPATH=/app

RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase build

CMD ["python", "-m", "workers.meshing.shape_as_points.worker", "--help"]
