#!/usr/bin/env bash
set -euo pipefail

INPUT_PATH="${1:-./examples/model_inputs/input.obj}"
OUTPUT_DIR="${2:-./examples/model_outputs}"
REPO_PATH="${3:-./external_models/ShapeAsPoints}"
CONFIG="${4:-configs/optim_based/teaser.yaml}"
TOTAL_EPOCHS="${5:-200}"
GRID_RES="${6:-128}"

bash ./examples/run_model_docker.sh \
  meshing \
  shape_as_points \
  "${INPUT_PATH}" \
  "${OUTPUT_DIR}" \
  "" \
  --repo-path "${REPO_PATH}" \
  --config "${CONFIG}" \
  --total-epochs "${TOTAL_EPOCHS}" \
  --grid-res "${GRID_RES}"
