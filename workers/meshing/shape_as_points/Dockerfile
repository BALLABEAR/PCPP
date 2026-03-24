FROM pcpp-runtime-cuda118:latest

WORKDIR /app

COPY workers/base/runtime /app/workers/base/runtime
COPY workers/meshing/shape_as_points/runtime.manifest.yaml /app/runtime.manifest.yaml
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase system
RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase python

COPY workers /app/workers
COPY external_models /app/external_models
ENV PYTHONPATH=/app

RUN python /app/workers/base/runtime/install_from_manifest.py --manifest /app/runtime.manifest.yaml --phase build

CMD ["python", "-m", "workers.meshing.shape_as_points.worker", "--help"]
