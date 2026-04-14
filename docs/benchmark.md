# Гайд по benchmark

## Что это

Benchmark в проекте нужен для измерения времени выполнения модели/пайплайна и потребления GPU.

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

## DAG-режим (через orchestrator)

```bash
python benchmark/run_benchmark.py \
  --model-id pipeline_flow \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --benchmark-target dag \
  --orchestrator-url http://localhost:8000 \
  --flow-id pipeline_flow \
  --flow-params-json "{}"
```

## Где смотреть результат

- Основной файл результата: `benchmark/results.json` (локальный, в git не хранится).
- Для DAG-режима дополнительно подтягиваются step-метрики из `pipeline_metrics.json` задачи.
