#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INPUT_PATH="${SCRIPT_DIR}/sample_input.txt"
OUTPUT_DIR="${SCRIPT_DIR}/out"

mkdir -p "${OUTPUT_DIR}"

cd "${PROJECT_ROOT}"
python -m workers.testing.sleep_worker.worker --input "${INPUT_PATH}" --output-dir "${OUTPUT_DIR}"

echo "Done. Check output in ${OUTPUT_DIR}"
