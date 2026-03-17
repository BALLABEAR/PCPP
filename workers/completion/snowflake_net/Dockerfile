FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app
ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9+PTX"

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev build-essential git cmake ninja-build \
    libx11-6 libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Install only required CUDA-compatible PyTorch (smaller + more stable download)
RUN python -m pip install --no-cache-dir --timeout 180 \
    --retries 20 \
    --resume-retries 20 \
    torch==2.1.2 \
    --index-url https://download.pytorch.org/whl/cu118

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
