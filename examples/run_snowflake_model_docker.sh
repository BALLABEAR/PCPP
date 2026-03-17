#!/usr/bin/env bash
set -euo pipefail

INPUT_PATH="${1:-./examples/model_inputs/input.xyz}"
WEIGHTS_PATH="${2:-./external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth}"
CONFIG_PATH="${3:-./external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml}"
OUTPUT_DIR="${4:-./examples/model_outputs}"
DEVICE="${5:-cuda}"
IMAGE_TAG="${6:-pcpp-snowflake:gpu}"

[[ -f "${INPUT_PATH}" ]] || { echo "Input file not found: ${INPUT_PATH}"; exit 1; }
[[ -f "${WEIGHTS_PATH}" ]] || { echo "Weights file not found: ${WEIGHTS_PATH}"; exit 1; }
[[ -f "${CONFIG_PATH}" ]] || { echo "Config file not found: ${CONFIG_PATH}"; exit 1; }

mkdir -p "${OUTPUT_DIR}"

docker build -t "${IMAGE_TAG}" -f workers/completion/snowflake_net/Dockerfile .

docker run --rm --gpus all \
  -v "$(pwd):/workspace" \
  -w /workspace \
  "${IMAGE_TAG}" \
  python -m workers.completion.snowflake_net.worker \
    --input "${INPUT_PATH}" \
    --output-dir "${OUTPUT_DIR}" \
    --mode model \
    --weights "${WEIGHTS_PATH}" \
    --config "${CONFIG_PATH}" \
    --device "${DEVICE}"

echo "Done. Output is in ${OUTPUT_DIR}"
