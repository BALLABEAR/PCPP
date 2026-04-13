FROM pcpp-runtime-cuda118:latest

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN if ! command -v python >/dev/null 2>&1; then       apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*;       ln -sf /usr/bin/python3 /usr/bin/python;     fi
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel pyyaml

COPY workers/base/runtime /app/workers/base/runtime
COPY workers/completion/poin_tr/runtime.manifest.yaml /app/runtime.manifest.yaml
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase system
COPY external_models /app/external_models
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase python

COPY workers /app/workers
ENV PYTHONPATH=/app

RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase build

CMD ["python", "-m", "workers.completion.poin_tr.worker", "--help"]
