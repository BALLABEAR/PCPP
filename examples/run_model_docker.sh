#!/usr/bin/env bash
set -euo pipefail

TASK_TYPE="${1:-}"
MODEL_ID="${2:-}"
INPUT_PATH="${3:-./examples/model_inputs/input.xyz}"
OUTPUT_DIR="${4:-./examples/model_outputs}"
IMAGE_TAG="${5:-}"

if [[ -z "${TASK_TYPE}" || -z "${MODEL_ID}" ]]; then
  echo "Usage: bash ./examples/run_model_docker.sh <task_type> <model_id> [input] [output] [image_tag] [extra_args...]"
  exit 1
fi

if [[ $# -ge 6 ]]; then
  MODEL_ARGS=("${@:6}")
else
  MODEL_ARGS=()
fi

[[ -f "${INPUT_PATH}" ]] || { echo "Input file not found: ${INPUT_PATH}"; exit 1; }
mkdir -p "${OUTPUT_DIR}"

DOCKERFILE_PATH="workers/${TASK_TYPE}/${MODEL_ID}/Dockerfile"
[[ -f "${DOCKERFILE_PATH}" ]] || { echo "Dockerfile not found: ${DOCKERFILE_PATH}"; exit 1; }

if [[ -z "${IMAGE_TAG}" ]]; then
  IMAGE_TAG="pcpp-${TASK_TYPE}-${MODEL_ID}:gpu"
fi

MODULE_NAME="workers.${TASK_TYPE}.${MODEL_ID}.worker"

docker build -t "${IMAGE_TAG}" -f "${DOCKERFILE_PATH}" .

docker run --rm --gpus all \
  -v "$(pwd):/workspace" \
  -w /workspace \
  "${IMAGE_TAG}" \
  python -m "${MODULE_NAME}" \
    --input "${INPUT_PATH}" \
    --output-dir "${OUTPUT_DIR}" \
    "${MODEL_ARGS[@]}"

echo "Done. Output is in ${OUTPUT_DIR}"
