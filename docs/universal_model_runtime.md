# Universal Model Runtime (docker-only)

Цель: запускать любые модели и любые `task_type` по единому сценарию, без ручной сборки окружения под каждую новую нейросеть.

## 1) Минимальный адаптер-контракт

Обязательные файлы для интеграции:

- `worker.py` — нормализованный интерфейс `--input` / `--output-dir`
- `model_card.yaml` — регистрация в реестре и параметры запуска

Рекомендуемые файлы (в docker-only архитектуре становятся стандартом):

- `runtime.manifest.yaml` — источник истины для зависимостей и build steps
- `Dockerfile` — универсальная сборка рантайма через manifest

## 2) runtime.manifest.yaml (универсальная схема)

Поддерживаемые секции:

- `base_image`: CUDA/Python базовый образ
- `system_packages`: apt-пакеты
- `python.pip`: список пакетов для `pip install`
- `python.pip_requirements_files`: список `-r` файлов
- `python.pip_commands`: произвольные pip-команды (для сложных случаев)
- `build_steps`: команды для сборки extension / пост-установки
- `env`: переменные окружения

Установка выполняется через:

- `workers/base/runtime/install_from_manifest.py --phase system`
- `workers/base/runtime/install_from_manifest.py --phase python`
- `workers/base/runtime/install_from_manifest.py --phase build`

## 3) Генератор адаптера для любой модели

Используйте:

```bash
python workers/base/create_model_adapter.py \
  --task-type meshing \
  --model-id my_model \
  --repo-path https://github.com/org/repo \
  --entry-command "python run.py --config cfg.yaml" \
  --input-format .obj,.ply \
  --output-format .ply
```

Что создается:

- `workers/<task_type>/<model_id>/worker.py`
- `workers/<task_type>/<model_id>/model_card.yaml`
- `workers/<task_type>/<model_id>/runtime.manifest.yaml`
- `workers/<task_type>/<model_id>/Dockerfile`
- `workers/<task_type>/<model_id>/README.generated.md`

## 4) Единый quick-run интерфейс

Windows:

```powershell
./examples/run_model_docker.ps1 -TaskType meshing -ModelId shape_as_points -InputPath ./examples/model_inputs/input.obj
```

Linux/macOS:

```bash
bash ./examples/run_model_docker.sh meshing shape_as_points ./examples/model_inputs/input.obj
```

Скрипты:

1. собирают Docker image из `workers/<task_type>/<model_id>/Dockerfile`
2. запускают `python -m workers.<task_type>.<model_id>.worker`
3. передают `--input` и `--output-dir`

## 5) Эталонный кейс: ShapeAsPoints optimization-based

Интеграция добавлена в:

- `workers/meshing/shape_as_points/worker.py`
- `workers/meshing/shape_as_points/model_card.yaml`
- `workers/meshing/shape_as_points/runtime.manifest.yaml`
- `workers/meshing/shape_as_points/Dockerfile`

Быстрый запуск:

Windows:

```powershell
./examples/run_shape_as_points_docker.ps1 -InputPath ./examples/model_inputs/input.obj
```

Linux/macOS:

```bash
bash ./examples/run_shape_as_points_docker.sh ./examples/model_inputs/input.obj
```

## 6) Почему это универсально

- Для новой модели меняется только `worker.py` и содержимое `runtime.manifest.yaml`.
- Docker-пайплайн и quick-run интерфейс остаются одинаковыми для любых `task_type`.
- Сложные dependency-кейсы (`pytorch3d`, `torch_scatter`, custom build`) описываются как данные в manifest, а не хардкодятся заново в каждом месте.
