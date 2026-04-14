# Point Cloud Processing Platform (PCPP)

PCPP is a modular platform for end-to-end point cloud processing with Docker-based model adapters, multi-step orchestration, and a minimal web UI.

Проект подходит для показа на собеседованиях: есть реальная orchestration-архитектура, API, frontend, расширяемый runtime для моделей и автотесты.

## Key Features

- **Pipeline orchestration**: FastAPI + Prefect for async workflows.
- **Unified worker contract**: `BaseWorker` for neural and non-neural tools.
- **Dynamic flow registration**: one source of truth in `flows/flow_definitions.py`.
- **Format-aware validation**: preflight compatibility checks for DAG steps.
- **Multi-file mode**: run a pipeline on `input_keys` (batch of files).
- **Benchmarking**: end-to-end + step-level metrics (queue/build/throughput).
- **Frontend**: upload, run, monitor, download.

## Architecture

```text
Frontend -> FastAPI Orchestrator -> Prefect Flows -> Dockerized Workers
                                  -> MinIO (input/results)
                                  -> PostgreSQL (tasks/pipelines/registry)
                                  -> Redis
```

## Tech Stack

- Python, FastAPI, Prefect
- Docker / Docker Compose
- PostgreSQL, Redis, MinIO
- Vanilla React frontend

## Quick Start

### Prerequisites

- Docker Desktop
- Python 3.10+ (for local tests/scripts)
- Git

### Run services

```bash
git clone <repo_url>
cd PCPP
cp .env.example .env
docker compose up -d --build
docker compose ps
```

### Open in browser

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| FastAPI | http://localhost:8000 |
| Prefect UI | http://localhost:4200 |
| MinIO Console | http://localhost:9001 |

Default MinIO credentials: `pcpp_minio / pcpp_minio_secret`.

## End-to-End Demo (Frontend)

1. Open `http://localhost:3000`.
2. Upload input point cloud.
3. Select a pipeline template.
4. Run task and wait for `completed`.
5. Download result.

## API Quick Example

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "input_bucket": "pcpp-files",
    "input_key": "uploads/example.xyz",
    "flow_id": "stage4_real_two_model_flow"
  }'
```

## Current Pipelines

- `stage2_test_flow`
- `stage4_segmentation_completion_flow` (legacy compatibility)
- `stage4_real_two_model_flow` (SnowflakeNet -> ShapeAsPoints)
- `stage4_snowflake_only_flow`
- `stage4_shape_as_points_only_flow`
- `stage4_cloudcompare_only_flow`
- `stage4_pointr_only_flow`

Templates for UI are exposed by `GET /pipelines/templates` and generated from `flows/flow_definitions.py`.

## Add a New Pipeline

Now this is one-place registration:

1. Create one flow file in `flows/` (one pipeline = one file).
2. Add one `FlowDefinition` in `flows/flow_definitions.py`:
   - `flow_id`
   - `flow_callable_path`
   - optional `step_builder_path` (for format validation)
   - optional `template` (for frontend list)

No manual sync is needed in `flows_registry`, `tasks`, `pipelines`, or `flow_validation`.

## Add a New Model Adapter

Recommended structure:

```text
workers/<task_type>/<model_id>/
  worker.py
  model_card.yaml
  Dockerfile (and/or runtime.manifest.yaml)
```

Scaffold generator:

```bash
python workers/base/create_model_adapter.py --help
```

Runtime layering contract:

- Generated adapters now default to `FROM pcpp-runtime-cuda118:latest`.
- Shared/common dependencies (CUDA toolchain, base Python tooling, torch/cu118) belong in `workers/base/runtime/Dockerfile.cuda118`.
- Model-specific dependencies belong in `workers/<task_type>/<model_id>/runtime.manifest.yaml`:
  - `python.pip` for Python packages specific to the model
  - `build_steps` for extension compilation/build commands
- During onboarding build, shared runtime is reused when present; if it is unavailable, build falls back to CUDA base image automatically.
- Keep model logic universal: avoid model-name-specific checks in onboarding and describe requirements through manifest + model card fields.

Ready-to-run adapter scripts:

- `examples/run_snowflake_model_docker.ps1` / `.sh`
- `examples/run_shape_as_points_docker.ps1` / `.sh`
- `examples/run_pointr_model_docker.ps1` / `.sh`

Important `model_card.yaml` fields:

- `accepted_input_formats`
- `produced_output_formats`
- `preferred_output_format`

## Testing

Install test dependencies:

```bash
pip install -r tests/requirements.txt
```

Run main test suite:

```bash
pytest tests/test_stage2_flow.py -v
pytest tests/test_stage3_worker_scaffold.py -v
pytest tests/test_stage4_flow.py -v
pytest tests/test_stage5_base_worker.py -v
pytest tests/test_stage6_frontend.py -v
pytest tests/test_stage5_6_architecture_hardening.py -v
```

## Benchmarking

Prepare benchmark data:

```bash
python benchmark/prepare_benchmark_data.py
```

Run DAG benchmark:

```bash
python benchmark/run_benchmark.py \
  --model-id stage4_real_pipeline \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --benchmark-target dag \
  --orchestrator-url http://localhost:8000 \
  --flow-id stage4_real_two_model_flow
```

Current metrics include:

- end-to-end elapsed
- queue delay
- per-step elapsed
- image build/cache info
- per-file throughput for batch runs

## Repository Layout (Short)

```text
orchestrator/   # API, DB models, task execution bridge
flows/          # flow files, common runtime logic, flow definitions
workers/        # base worker + model/tool adapters
frontend/       # web UI
benchmark/      # benchmark runner/results
docs/           # integration and runtime guides
tests/          # unit/integration/smoke tests
```

## Documentation

- `docs/model_and_pipeline_quickstart_ru.md`

## Operational Notes

- Heavy models/repos should stay in `external_models/` (gitignored).
- Stop services: `docker compose down`
- Stop and remove volumes: `docker compose down -v`
