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

