#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INPUT_PATH="${SCRIPT_DIR}/model_inputs/input.xyz"
OUTPUT_DIR="${SCRIPT_DIR}/model_outputs"

mkdir -p "${OUTPUT_DIR}"

cd "${PROJECT_ROOT}"
python -m workers.segmentation.fake_segmentation.worker --input "${INPUT_PATH}" --output-dir "${OUTPUT_DIR}"

echo "Done. Check output in ${OUTPUT_DIR}"
