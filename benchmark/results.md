# Stage 3 Benchmark Results

Заполните таблицу после запуска реального инференса модели.

## Temporary Benchmark (current)

Временный режим на 3 пользовательских файлах:

| Model | Input File | Inference Time (s) | Peak GPU Memory (MB) | Notes |
|------|------------|--------------------|----------------------|-------|
| snowflake_net | sofa.pcd | TODO | TODO | |
| snowflake_net | input.ply | TODO | TODO | |
| snowflake_net | airplane.pcd | TODO | TODO | |

<!--
Future production benchmark (will be used later):
| Model | Input Size | Inference Time (s) | Peak GPU Memory (MB) | Notes |
|------|------------|--------------------|----------------------|-------|
| my_model_id | 100K | TODO | TODO | |
| my_model_id | 500K | TODO | TODO | |
| my_model_id | 1M | TODO | TODO | |
-->

## How to run temporary benchmark

```bash
python benchmark/run_benchmark.py \
  --model-id snowflake_net \
  --use-local-samples \
  --repeats 1 \
  --run-command-template "powershell -ExecutionPolicy Bypass -File ./examples/run_snowflake_model_docker.ps1 -InputPath {input}"
```

Результаты будут добавлены в `benchmark/results.json`.

## Production benchmark (later)

Раскомментируйте блок выше и используйте таблицу 100K/500K/1M после перехода к полноценным dataset-прогонам.

## Методика

- Выполните по 3 прогона на каждый размер входа.
- В таблицу заносите среднее время.
- Пиковую память фиксируйте через `nvidia-smi`.
