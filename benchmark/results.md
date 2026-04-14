# Stage 3 Benchmark Results

Итоги зафиксированы на основе `benchmark/results.json`.

## Prepared dataset benchmark (Stage 3 done)

Датасет: `prepared_dataset`, 3 файла на каждый размер, `repeats=1`.

| Model | Input Size | Runs | Avg Inference Time (s) | Min Time (s) | Max Time (s) | Peak GPU Memory Max (MB) | Notes |
|------|------------|------|-------------------------|--------------|--------------|--------------------------|-------|
| snowflake_net | 100k | 3 | 30.286 | 4.174 | 80.132 | 921 | one outlier run |
| snowflake_net | 500k | 3 | 31.830 | 4.327 | 86.401 | 1024 | one outlier run |
| snowflake_net | 1m | 3 | 4.643 | 4.565 | 4.752 | 1029 | stable |

### Raw run details (prepared dataset)

| Input Size | Input File | Inference Time (s) | Peak GPU Memory (MB) |
|------------|------------|--------------------|----------------------|
| 100k | room_scan1_100k.xyz | 6.553 | 921 |
| 100k | table_scene_lms400_100k.xyz | 80.132 | 909 |
| 100k | table_scene_mug_stereo_textured_100k.xyz | 4.174 | 909 |
| 500k | room_scan1_500k.xyz | 4.761 | 925 |
| 500k | table_scene_lms400_500k.xyz | 86.401 | 1024 |
| 500k | table_scene_mug_stereo_textured_500k.xyz | 4.327 | 1024 |
| 1m | room_scan1_1m.xyz | 4.565 | 1024 |
| 1m | table_scene_lms400_1m.xyz | 4.611 | 1029 |
| 1m | table_scene_mug_stereo_textured_1m.xyz | 4.752 | 803 |

## Temporary benchmark (archive)

Первичный режим на 3 пользовательских файлах (оставлен как историческая запись):

| Model | Input File | Inference Time (s) | Peak GPU Memory (MB) | Notes |
|------|------------|--------------------|----------------------|-------|
| snowflake_net | sofa.pcd | 79.898 | 1510 | local sample |
| snowflake_net | input.ply | 5.768 | 1481 | local sample |
| snowflake_net | airplane.pcd | 5.632 | 1481 | local sample |

## How to run temporary benchmark

```bash
python benchmark/run_benchmark.py \
  --model-id snowflake_net \
  --use-local-samples \
  --repeats 1 \
  --run-command-template "powershell -ExecutionPolicy Bypass -File ./examples/run_snowflake_model_docker.ps1 -InputPath {input}"
```

Результаты будут добавлены в `benchmark/results.json`.

## Prepared benchmark dataset (recommended)

### 1) Подготовка данных одной командой

```bash
python benchmark/prepare_benchmark_data.py
```

Скрипт:

- скачает эталонные raw-файлы в `data/raw_benchmark/`,
- проверит `sha256`,
- подготовит `.xyz` наборы в `data/benchmark_inputs/{100k,500k,1m}`,
- запишет манифесты в `data/benchmark_manifests/`.

### 2) Запуск benchmark на prepared-данных

```bash
python benchmark/run_benchmark.py \
  --model-id snowflake_net \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --run-command-template "powershell -ExecutionPolicy Bypass -File ./examples/run_snowflake_model_docker.ps1 -InputPath {input}"
```

## Stage 4 real DAG benchmark (completion -> meshing)

Для закрытия этапа 4 benchmark снимается с реального пайплайна `stage4_real_two_model_flow`, а не с отдельной модели.

```bash
python benchmark/run_benchmark.py \
  --model-id stage4_real_pipeline \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --benchmark-target dag \
  --orchestrator-url http://localhost:8000 \
  --flow-id stage4_real_two_model_flow \
  --flow-params-json "{\"completion_mode\":\"model\",\"completion_weights_path\":\"external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth\",\"completion_config_path\":\"external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml\",\"completion_device\":\"cuda\",\"meshing_repo_path\":\"external_models/ShapeAsPoints\",\"meshing_config_path\":\"configs/optim_based/teaser.yaml\",\"meshing_total_epochs\":200,\"meshing_grid_res\":128,\"meshing_no_cuda\":false}"
```

В `benchmark/results.json` для `mode=prepared_dataset_dag` записываются:

- `elapsed_seconds` — end-to-end время DAG,
- `step_metrics` — длительность и GPU snapshot по каждому шагу,
- `task_id`, `task_result_key`, `flow_id` — трассировка прогона.

## Production benchmark (later)
При новых прогонах фиксируйте значения в `benchmark/results.json` и обновляйте агрегированную таблицу в этом файле.

## Методика

- Выполните по 3 прогона на каждый размер входа.
- В таблицу заносите среднее время.
- Пиковую память фиксируйте через `nvidia-smi`.
