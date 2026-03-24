# Stage 3: Add Any GitHub Model (Beginner Friendly)

Этот документ состоит из двух уровней:

- **Quick Start**: быстрый сценарий для любого пользователя (через fake-модель).
- **Template Section**: шаблоны файлов для подключения любой реальной модели из GitHub.

## Quick Start (5-7 шагов)

### 1) Поднимите сервисы

```bash
docker compose up -d --build
```

### 2) Убедитесь, что Python-зависимости для тестов стоят

```bash
pip install -r tests/requirements.txt
```

### 3) Запустите fake-модель как обычный скрипт

Windows (PowerShell):

```powershell
./examples/run_fake_model.ps1
```

Linux/macOS:

```bash
bash ./examples/run_fake_model.sh
```

### 4) Проверьте, что создан выходной файл

Ожидаемая папка: `examples/out/`

### 5) Проверьте, что модель видна в реестре

```bash
curl http://localhost:8000/registry/models
```

Ищите `id: sleep_worker`.

### 6) Прогоните тест onboarding-каркаса

```bash
pytest tests/test_stage3_worker_scaffold.py -v
```

Если тест зеленый, значит инфраструктура подключения модели работает.

---

## Пример: куда скачивать SnowflakeNet и что делать дальше

Ниже конкретный путь для ситуации "я открыл GitHub и не понимаю куда копировать":

### 1) Скачайте внешний репозиторий ВНЕ `workers/`

```bash
mkdir -p external_models
git clone https://github.com/AllenXiangX/SnowflakeNet external_models/SnowflakeNet
```

Важно: внешний код храните в `external_models/`, а не в `workers/`.
`external_models/` уже в `.gitignore`, поэтому тяжелые файлы не попадут в git.

### 2) Создайте обертку под PCPP

Внутри PCPP создайте свою папку:

`workers/completion/snowflake_net/`

И добавьте 4 файла:

- `worker.py`
- `model_card.yaml`
- `requirements.txt`
- `Dockerfile`

### 3) Перенесите только нужный код в `worker.py`

Не копируйте весь репозиторий SnowflakeNet в `workers/`.
В `worker.py` оставьте только интеграционный слой:

1. загрузка весов,
2. вызов инференса из внешнего кода (`external_models/SnowflakeNet/...`),
3. сохранение результата.

### 4) Учитывайте особенности SnowflakeNet из их README

У SnowflakeNet в оригинале указан стек под старую среду (например Python 3.7, PyTorch 1.7.1, CUDA 11.0 и сборка расширений `pointnet2_ops`, `Chamfer3D`, `emd`).
Это не значит, что надо менять весь PCPP под 3.7. Правильный путь:

- изолировать эти зависимости в Dockerfile конкретного воркера,
- проверить сборку расширений внутри контейнера воркера,
- не смешивать зависимости SnowflakeNet с orchestrator/tests.

### 5) Папка для пользовательских тестов модели

Используйте:

- `examples/model_inputs/` — входные тестовые облака (например `sofa.pcd`, `input.ply`, `airplane.pcd`)
- `examples/model_outputs/` — результаты запуска

Готовые скрипты:

- Windows: `./examples/run_snowflake_model.ps1`
- Linux/macOS: `bash ./examples/run_snowflake_model.sh`

Текущий Snowflake wrapper уже умеет читать `.pcd`, `.ply`, `.xyz`, `.txt`, `.npy`.

---

## Рекомендуемый способ для "чтобы точно работало": Docker GPU

Если локальная сборка в `.venv` падает (CUDA_HOME, pointnet2_ops, torch), используйте готовый docker-сценарий.

### Windows

```powershell
./examples/run_snowflake_model_docker.ps1
```

### Linux/macOS

```bash
bash ./examples/run_snowflake_model_docker.sh
```

Что делает скрипт:

1. Собирает GPU-образ из `workers/completion/snowflake_net/Dockerfile`
2. Устанавливает PyTorch + CUDA и собирает расширение `pointnet2_ops` внутри контейнера
3. Запускает инференс и пишет результат в `examples/model_outputs/`

Примечание: `Chamfer3D` и `EMD` нужны в основном для train/eval loss и в инференс-образ не включены для повышения стабильности сборки.

Требования:

- Docker Desktop / Docker Engine
- NVIDIA Container Toolkit (доступ к GPU из Docker)
- драйвер NVIDIA на хосте

---

## Template Section: как подключить любую модель из GitHub

## 1) Выберите модель и зафиксируйте источник

- Сохраните URL репозитория.
- Зафиксируйте commit/tag для воспроизводимости.
- Проверьте лицензию.
- Выпишите требования:
  - формат входа/выхода,
  - лимиты по числу точек,
  - GPU/VRAM,
  - версию Python/CUDA/PyTorch.

## 2) Создайте структуру папки модели

Используйте путь:

`workers/<task_type>/<model_name>/`

Минимальный набор файлов:

- `worker.py`
- `model_card.yaml`
- `requirements.txt`
- `Dockerfile`

## 3) Шаблон worker.py

```python
from pathlib import Path
from workers.base.base_worker import BaseWorker


class MyModelWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(model_id="my_model_id")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_path = output_dir / f"{input_path.stem}_result{input_path.suffix or '.ply'}"

        # 1) load weights
        # 2) load point cloud
        # 3) run inference
        # 4) save result
        output_path.write_bytes(input_path.read_bytes())  # replace with real inference
        return output_path
```

## 4) Шаблон model_card.yaml

```yaml
id: my_model_id
name: MyModel
task_type: completion
description: >
  Short model description.
input_format: [.ply, .pcd]
output_format: [.ply]
min_points: 512
max_points: 16384
gpu_required: true
gpu_memory_mb: 4000
max_points_per_batch: 2048
batching_mode: auto
speed: medium
quality: high
github_url: https://github.com/org/repo
params:
  example_param:
    type: int
    default: 1
    min: 1
    max: 16
    description: Example parameter
```

## 5) Шаблон requirements.txt

```txt
numpy>=1.26
torch==2.2.0
```

## 6) Шаблон Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY workers/<task_type>/<model_name>/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY workers /app/workers
ENV PYTHONPATH=/app

CMD ["python", "-m", "workers.<task_type>.<model_name>.worker", "--help"]
```

## 7) Проверка после подключения

1. Локальный smoke-test `worker.py` на маленьком файле.
2. `docker build` вашего воркера.
3. `curl /registry/models` и проверка `id`.
4. Замеры через `benchmark/run_benchmark.py`.
5. Фиксация результатов в `benchmark/results.md`.

### Benchmark data (одна команда)

Чтобы получить воспроизводимые входы `100K/500K/1M`, выполните:

```bash
python scripts/prepare_benchmark_data.py
```

Это создаст локальные папки:

- `data/raw_benchmark/`
- `data/benchmark_inputs/{100k,500k,1m}/`
- `data/benchmark_manifests/`

Запуск benchmark на prepared dataset:

```bash
python benchmark/run_benchmark.py \
  --model-id snowflake_net \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --run-command-template "powershell -ExecutionPolicy Bypass -File ./examples/run_snowflake_model_docker.ps1 -InputPath {input}"
```

---

## Troubleshooting (частые ошибки и решения)

### `{"detail":"Not Found"}` на `http://localhost:8000/registry/models`

Причина: запущен старый orchestrator-контейнер без нового роута.

Решение:

```bash
docker compose up -d --build orchestrator
```

### `ModuleNotFoundError: No module named 'workers'` при pytest

Причина: тесты запущены не из корня проекта или не настроен путь импорта.

Решение:

- запускать из корня `PCPP`
- использовать `python -m pytest ...`
- в проекте уже есть `tests/conftest.py` для авто-добавления корня в `sys.path`

### `unexpected EOF` / `short read` во время `docker build`

Причина: обрыв сети/битый кэш Docker при скачивании больших слоев.

Решение:

```bash
docker builder prune -af
docker image prune -af
docker pull nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04
```

и повторить запуск скрипта.

### `CUDA_HOME environment variable is not set` при локальной сборке extension

Причина: локальный `.venv` не видит CUDA toolkit.

Решение:

- использовать Docker GPU-скрипт (рекомендуется),
- или настраивать локальный CUDA toolkit и `CUDA_HOME` вручную.

### `No module named 'pointnet2_ops'`

Причина: не собран extension SnowflakeNet.

Решение:

- в Docker-режиме extension собирается автоматически,
- в локальном режиме нужно выполнять `setup.py install` в `models/pointnet2_ops_lib`.

### Ошибка Open3D в контейнере (`libX11.so.6` и т.п.)

Причина: не хватает системных Linux-библиотек для Open3D.

Решение:

- использовать актуальный Dockerfile из проекта (в нем зависимости уже добавлены),
- пересобрать образ.

### Ошибка пути в Docker (`Input file not found: .\\examples\\...`)

Причина: в Linux-контейнер передан Windows-стиль пути.

Решение:

- используйте обновленный `run_snowflake_model_docker.ps1`,
- передавайте пути в формате `./examples/...`.

### `NameError: np is not defined`

Причина: баг импорта в обертке.

Решение:

- исправлено в текущем `worker.py`,
- пересоберите образ перед повторным запуском.

