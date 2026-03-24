FROM pcpp-runtime-cuda118:latest

WORKDIR /app
ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9+PTX"

COPY workers/completion/snowflake_net/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY workers /app/workers
COPY external_models /app/external_models

# Build only inference-required SnowflakeNet extension.
# Chamfer3D/EMD are mainly needed for training/evaluation losses and are skipped here.
RUN cd /app/external_models/SnowflakeNet/models/pointnet2_ops_lib && python setup.py install

ENV PYTHONPATH=/app
ENV SNOWFLAKE_REPO=/app/external_models/SnowflakeNet

CMD ["python", "-m", "workers.completion.snowflake_net.worker", "--help"]
