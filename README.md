# Point Cloud Processing Platform (PCPP)

Модульная платформа для обработки облаков точек с кастомными пайплайнами.

## Быстрый старт (Этап 2)

### Требования
- Docker Desktop
- Python 3.11+
- Git

### Запуск сервисов

```bash
# 1. Клонировать репозиторий
git clone <repo_url>
cd pcpp

# 2. Создать .env из примера
cp .env.example .env
# Отредактировать .env при необходимости

# 3. Поднять сервисы этапа 2
docker compose up -d --build

# 4. Проверить что всё запустилось
docker compose ps
```

### Проверка готовности (тесты)

```bash
# Установить зависимости для тестов
pip install -r tests/requirements.txt

# Запустить тесты этапа 1 (инфраструктура)
pytest tests/test_infrastructure.py -v

# Запустить тест этапа 2 (сквозной сценарий)
pytest tests/test_stage2_flow.py -v

# Запустить тест onboarding-каркаса этапа 3 (fake sleep_worker)
pytest tests/test_stage3_worker_scaffold.py -v

# Запустить интеграционный тест этапа 4 (DAG segmentation -> completion)
pytest tests/test_stage4_flow.py -v

# Запустить unit-тесты этапа 5 (robust BaseWorker)
pytest tests/test_stage5_base_worker.py -v

# Запустить тесты этапа 6 (frontend + pipeline templates API)
pytest tests/test_stage6_frontend.py -v
```

Все тесты должны быть зелёными.

### Доступ к сервисам

| Сервис     | Адрес                  | Логин/Пароль                    |
|------------|------------------------|---------------------------------|
| MinIO UI   | http://localhost:9001  | pcpp_minio / pcpp_minio_secret  |
| PostgreSQL | localhost:5433         | pcpp_user / pcpp_password       |
| Redis      | localhost:6379         | —                               |
| FastAPI    | http://localhost:8000  | —                               |
| Prefect UI | http://localhost:4200  | —                               |
| Frontend   | http://localhost:3000  | —                               |

### Остановка

```bash
docker compose down          # остановить, данные сохранятся
docker compose down -v       # остановить и удалить все данные
```

---

## Структура проекта

```
pcpp/
├── docker-compose.yml              # Фаза 1 — ядро системы
├── docker-compose.observability.yml# Фаза 1 — MLflow, Prometheus, Grafana (этап 8)
├── docker-compose.phase2.yml       # Фаза 2 — Triton и др.
├── .env                            # локальные секреты (не коммитится)
├── .env.example                    # шаблон для .env
├── requirements-dev.txt            # локальные dev-зависимости
├── tests/
│   ├── requirements.txt
│   ├── test_infrastructure.py      # тесты этапа 1
│   ├── test_stage2_flow.py         # интеграционный тест этапа 2
│   ├── test_stage3_worker_scaffold.py # проверка onboarding scaffolds этапа 3
│   ├── test_stage4_flow.py         # интеграционный тест DAG этапа 4
│   ├── test_stage5_base_worker.py  # unit-тесты BaseWorker stage 5
│   └── test_stage6_frontend.py     # smoke + API тесты frontend stage 6
├── orchestrator/
│   ├── main.py                     # точка входа FastAPI + подключение роутеров
│   ├── api/
│   │   ├── files.py                # загрузка / скачивание файлов
│   │   ├── tasks.py                # запуск задачи и статус
│   │   ├── pipelines.py            # API пайплайнов
│   │   └── registry.py             # API реестра моделей
│   ├── models/
│   │   ├── pipeline.py
│   │   ├── task.py
│   │   └── model_card.py
│   ├── registry/scanner.py         # сканирование model_card.yaml
│   ├── prefect_client.py           # единая точка связи FastAPI -> Prefect flow
│   └── ...
├── flows/
│   ├── pipeline_flow.py            # тестовый flow (MinIO -> sleep 5s -> MinIO)
│   └── flows_registry.py           # реестр flow для orchestrator
├── frontend/
│   ├── Dockerfile
│   └── src/
│       ├── index.html
│       ├── app.js
│       └── styles.css
├── workers/testing/sleep_worker/
│   ├── worker.py                   # fake-модель для onboarding
│   ├── model_card.yaml
│   ├── requirements.txt
│   └── Dockerfile
├── workers/segmentation/fake_segmentation/
│   ├── worker.py                   # fake segmentation шаг для Stage 4 DAG
│   ├── model_card.yaml
│   ├── requirements.txt
│   └── Dockerfile
├── workers/base/base_worker.py     # базовый контракт для будущих ML-воркеров
├── workers/completion/             # пользовательские completion-модели (gitignored)
├── workers/segmentation/           # пользовательские segmentation-модели (gitignored)
├── workers/meshing/                # пользовательские meshing-модели (gitignored)
├── benchmark/
│   ├── run_benchmark.py            # шаблон запуска замеров
│   └── results.md                  # шаблон фиксации результатов
├── scripts/
│   └── prepare_benchmark_data.py   # auto-download и подготовка 100K/500K/1M
├── docs/
│   ├── adding_github_model_stage3.md
│   └── universal_model_runtime.md   # docker-only универсальный runtime для любых моделей
├── examples/
│   ├── run_model_docker.ps1        # универсальный docker-run для любой модели (Windows)
│   ├── run_model_docker.sh         # универсальный docker-run для любой модели (Linux/macOS)
│   ├── run_shape_as_points_docker.ps1 # готовый запуск ShapeAsPoints (Windows)
│   ├── run_shape_as_points_docker.sh  # готовый запуск ShapeAsPoints (Linux/macOS)
│   ├── run_snowflake_model_docker.ps1 # запуск Snowflake через GPU Docker (Windows)
│   ├── run_snowflake_model_docker.sh  # запуск Snowflake через GPU Docker (Linux/macOS)
│   ├── model_inputs/               # сюда кладутся пользовательские test-файлы
│   ├── model_outputs/              # результаты (gitignored)
│   └── sample_input.txt
├── workers/base/
│   ├── create_model_adapter.py     # генератор scaffold для любой новой модели
│   └── runtime/install_from_manifest.py # применение runtime.manifest.yaml
├── workers/meshing/shape_as_points/
│   ├── worker.py                   # адаптер ShapeAsPoints (optimization-based)
│   ├── model_card.yaml
│   ├── runtime.manifest.yaml
│   ├── Dockerfile
│   └── README.md
└── ...
```

---

## Этапы разработки

### Фаза 1
- [x] **Этап 1** — Инфраструктура: PostgreSQL, Redis, MinIO
- [x] **Этап 2** — FastAPI + Prefect + тестовый воркер
- [x] **Этап 3** — Первая нейросеть + бенчмарк
- [ ] **Этап 4** — Вторая модель + DAG
- [x] **Этап 5** — Robustness BaseWorker
- [x] **Этап 6** — Frontend
- [ ] **Этап 7** — Третья модель + валидация + GPU-очереди
- [ ] **Этап 8** — Observability

### Фаза 2
- [ ] Triton Inference Server
- [ ] Дообучение моделей
- [ ] Версионирование датасетов (DVC)
- [ ] Spatial chunking
- [ ] Кэширование узлов
- [ ] Отказоустойчивость
- [ ] Свой Frontend
- [ ] CI/CD

---

## Что реализовано в Этапе 2

- FastAPI endpoints:
  - `POST /files/upload` — загрузка входного файла в MinIO (`pcpp-files`)
  - `GET /files/download` — получение временной ссылки на скачивание из MinIO
  - `POST /tasks` — создание задачи и запуск Prefect flow
  - `GET /tasks/{task_id}` — получение статуса (`pending/running/completed/failed`)
- SQLAlchemy модели: `Task`, `Pipeline`, `ModelCard`
- Сканер `model_card.yaml` при старте orchestrator
- Prefect flow `stage2-test-flow`: скачивает файл из MinIO, ждёт 5 секунд, сохраняет копию в `pcpp-results`
- Базовое логирование в orchestrator и во flow

---

## Этап 3 (выполнено)

- Добавлен универсальный `BaseWorker` (`workers/base/base_worker.py`)
- Добавлена fake-модель `workers/testing/sleep_worker` для простого onboarding
- Добавлен шаблон benchmark-скрипта и таблицы результатов
- Добавлен тест `tests/test_stage3_worker_scaffold.py`
- Добавлен гайд `docs/adding_github_model_stage3.md` в формате:
  - Quick Start для новичков
  - Template Section для подключения любой модели из GitHub
- Добавлены `examples/` для запуска fake-модели без написания кода
- Добавлен reproducible benchmark pipeline (`prepare_benchmark_data.py` + `run_benchmark.py --dataset prepared`)
- Зафиксированы benchmark-результаты в `benchmark/results.md` и `benchmark/results.json`

## Критерии Done для Этапа 3

- `sleep_worker` виден в `/registry/models` и проходит `tests/test_stage3_worker_scaffold.py`
- Snowflake worker запускается через локальный wrapper или Docker-скрипт
- Данные benchmark 100K/500K/1M готовятся одной командой
- Результаты benchmark сохраняются в `benchmark/results.json` и агрегируются в `benchmark/results.md`

Команда быстрой проверки:

```bash
python scripts/prepare_benchmark_data.py
python benchmark/run_benchmark.py \
  --model-id snowflake_net \
  --dataset prepared \
  --input-size 100k \
  --repeats 1 \
  --run-command-template "powershell -ExecutionPolicy Bypass -File ./examples/run_snowflake_model_docker.ps1 -InputPath {input}"
```

## Для пользователей без опыта

- Начните с `docs/adding_github_model_stage3.md` (раздел Quick Start)
- Для smoke-проверки используйте универсальный запуск:
  `examples/run_model_docker.ps1 -TaskType testing -ModelId sleep_worker ...`
- Если локальный Python не собирает CUDA-расширения, используйте Docker-вариант:
  `examples/run_snowflake_model_docker.ps1` (или `.sh`)
- Проверяйте работоспособность через `tests/test_stage3_worker_scaffold.py`

## Этап 4 (итерация 1)

- Добавлен flow `stage4_real_two_model_flow` (реальный DAG из двух моделей)
- Шаг 1: `SnowflakeWorker` (`workers/completion/snowflake_net`)
- Шаг 2: `ShapeAsPointsOptimWorker` (`workers/meshing/shape_as_points`)
- Legacy flow `stage4_segmentation_completion_flow` оставлен для обратной совместимости.
- В `POST /tasks` можно указать:
  - `flow_id` (по умолчанию `stage2_test_flow`)
  - `flow_params` (опциональные параметры для выбранного flow)

Пример запуска Stage 4 задачи:

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "input_bucket": "pcpp-files",
    "input_key": "uploads/example.xyz",
    "flow_id": "stage4_real_two_model_flow",
    "flow_params": {
      "completion_mode": "model",
      "completion_weights_path": "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
      "completion_config_path": "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
      "completion_device": "cuda",
      "meshing_repo_path": "external_models/ShapeAsPoints",
      "meshing_config_path": "configs/optim_based/teaser.yaml",
      "meshing_total_epochs": 200,
      "meshing_grid_res": 128,
      "meshing_no_cuda": false
    }
  }'
```

### Benchmark Stage 4 (снимать с DAG)

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

## Универсальный запуск моделей (docker-only)

- Для новой модели используйте генератор:
  `python workers/base/create_model_adapter.py ...`
- Runtime описывается в `runtime.manifest.yaml` (зависимости, build steps, env).
- Docker-сборка выполняется универсально через `workers/base/runtime/install_from_manifest.py`.
- Единый запуск любой модели:
  - `./examples/run_model_docker.ps1 -TaskType <task> -ModelId <model> ...`
  - `bash ./examples/run_model_docker.sh <task> <model> ...`
- Эталонный адаптер `ShapeAsPoints` (task_type `meshing`) добавлен в
  `workers/meshing/shape_as_points`.
- Полный гайд:
  `docs/universal_model_runtime.md`

## Tests vs Examples

- `tests/` — автотесты для CI и технической проверки.
- `examples/` — пошаговые учебные сценарии для пользователей.

## Где хранить реальные модели

- Репозитории моделей (скачанные с GitHub) храните в `external_models/` (папка в `.gitignore`).
- Рабочие обертки под PCPP кладите в `workers/<task_type>/<model_name>/`.
- Папки `workers/completion`, `workers/segmentation`, `workers/meshing` по умолчанию игнорируются git, чтобы в репозиторий не попадали тяжелые модели/веса.

## Benchmark data policy

- Локальные benchmark-данные не хранятся в git.
- Используйте `data/raw_benchmark/`, `data/benchmark_inputs/`, `data/benchmark_manifests/`.
- Подготовка одной командой:

```bash
python scripts/prepare_benchmark_data.py
```

## Файлы зависимостей

- `orchestrator/requirements.txt` — зависимости runtime оркестратора
- `tests/requirements.txt` — зависимости для тестов
- `requirements-dev.txt` — локальные dev-зависимости