#!/usr/bin/env bash
set -euo pipefail

INPUT_PATH="${1:-./examples/model_inputs/input.xyz}"
WEIGHTS_PATH="${2:-./external_models/PoinTr/pretrained/PoinTr_PCN.pth}"
CONFIG_PATH="${3:-cfgs/PCN_models/PoinTr.yaml}"
REPO_PATH="${4:-./external_models/PoinTr}"
OUTPUT_DIR="${5:-./examples/model_outputs}"
DEVICE="${6:-cuda:0}"

[[ -f "${INPUT_PATH}" ]] || { echo "Input file not found: ${INPUT_PATH}"; exit 1; }
[[ -f "${WEIGHTS_PATH}" ]] || { echo "Weights file not found: ${WEIGHTS_PATH}"; exit 1; }
[[ -d "${REPO_PATH}" ]] || { echo "Repo path not found: ${REPO_PATH}"; exit 1; }
[[ -f "${REPO_PATH}/${CONFIG_PATH}" ]] || { echo "Config file not found: ${REPO_PATH}/${CONFIG_PATH}"; exit 1; }

bash ./examples/run_model_docker.sh \
  completion \
  poin_tr \
  "${INPUT_PATH}" \
  "${OUTPUT_DIR}" \
  "" \
  --mode model \
  --repo-path "${REPO_PATH}" \
  --config "${CONFIG_PATH}" \
  --weights "${WEIGHTS_PATH}" \
  --device "${DEVICE}"
