# Гайд по benchmark и работе pipeline

## Что это

Benchmark в проекте нужен для измерения времени выполнения модели/пайплайна и потребления GPU.

## Как устроен pipeline в проекте

Актуальный runtime-пайплайн:

`Frontend/API client -> FastAPI Orchestrator -> pipeline_flow (Prefect) -> Docker workers -> MinIO`

Что происходит по шагам:

1. Пайплайн создается через API `POST /pipelines/validate-draft` и `POST /pipelines/create-draft`.
2. Для каждого шага orchestrator:
   - берет `model_id` из реестра;
   - проверяет readiness (build/smoke);
   - строит runtime-конфиг шага (`worker_module`, `worker_class`, `dockerfile_path`, `image_tag`, `cli_args`);
   - проверяет совместимость форматов `output -> input` между соседними шагами.
3. Запуск выполняется через `POST /tasks`:
   - входной файл уже лежит в MinIO (`/files/upload`);
   - создается запись задачи в БД со статусом `pending`;
   - поднимается flow `pipeline_flow`.
4. Во `flows/common.py` функция `execute_pipeline`:
   - последовательно гоняет шаги;
   - каждый шаг выполняется `run_worker_step` (обычно в Docker);
   - вход шага скачивается из MinIO, выход шага загружается обратно в MinIO;
   - после последнего шага результат копируется в `results/<task_id>/pipeline_output.*`.
5. По завершению сохраняются метрики в `results/<task_id>/pipeline_metrics.json`:
   - `elapsed_seconds`, `queue_delay_seconds`;
   - `image_build_total_seconds`, `image_cache_hits`;
   - `throughput_files_per_second`, `files_total`;
   - пошаговые метрики (`steps`) и метрики по элементам батча (`items`).

## Подготовка данных

```bash
python benchmark/prepare_benchmark_data.py
```

Скрипт:

- скачивает исходные `.pcd` файлы;
- проверяет контрольные суммы;
- готовит наборы `100k`, `500k`, `1m` в `data/benchmark_inputs`;
- пишет манифесты в `data/benchmark_manifests`.

## Запуск benchmark на подготовленных данных

```bash
python benchmark/run_benchmark.py \
  --model-id my_model \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --run-command-template "python your_runner.py --input {input}"
```

## DAG-режим benchmark (через orchestrator)

```bash
python benchmark/run_benchmark.py \
  --model-id pipeline_flow \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --benchmark-target dag \
  --orchestrator-url http://localhost:8000 \
  --flow-id pipeline_flow \
  --flow-params-json "{\"pipeline_steps\": [...]}"
```

Что делает DAG-режим:

1. Загружает вход в MinIO через `POST /files/upload`.
2. Создает задачу через `POST /tasks`.
3. Поллит `GET /tasks/{task_id}` до `completed/failed`.
4. Забирает `pipeline_metrics.json` через `/files/download` и добавляет метрики в `benchmark/results.json`.

## Где смотреть результат

- Основной файл: `benchmark/results.json` (локальный, в git не хранится).
- Runtime-метрики пайплайна: `results/<task_id>/pipeline_metrics.json` в MinIO.
