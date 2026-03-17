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
│   └── test_infrastructure.py      # тесты этапа 1
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
├── workers/testing/sleep_worker/
│   ├── worker.py                   # fake-модель для onboarding
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
├── docs/
│   └── adding_github_model_stage3.md
├── examples/
│   ├── run_fake_model.ps1          # быстрый запуск fake-модели (Windows)
│   ├── run_fake_model.sh           # быстрый запуск fake-модели (Linux/macOS)
│   ├── run_snowflake_model.ps1     # запуск Snowflake wrapper (Windows)
│   ├── run_snowflake_model.sh      # запуск Snowflake wrapper (Linux/macOS)
│   ├── run_snowflake_model_docker.ps1 # запуск Snowflake через GPU Docker (Windows)
│   ├── run_snowflake_model_docker.sh  # запуск Snowflake через GPU Docker (Linux/macOS)
│   ├── model_inputs/               # сюда кладутся пользовательские test-файлы
│   ├── model_outputs/              # результаты (gitignored)
│   └── sample_input.txt
└── ...
```

---

## Этапы разработки

### Фаза 1
- [x] **Этап 1** — Инфраструктура: PostgreSQL, Redis, MinIO
- [x] **Этап 2** — FastAPI + Prefect + тестовый воркер
- [ ] **Этап 3** — Первая нейросеть + бенчмарк
- [ ] **Этап 4** — Вторая модель + DAG
- [ ] **Этап 5** — Robustness BaseWorker
- [ ] **Этап 6** — Frontend
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

## Подготовка к Этапу 3 (scaffold)

- Добавлен универсальный `BaseWorker` (`workers/base/base_worker.py`)
- Добавлена fake-модель `workers/testing/sleep_worker` для простого onboarding
- Добавлен шаблон benchmark-скрипта и таблицы результатов
- Добавлен тест `tests/test_stage3_worker_scaffold.py`
- Добавлен гайд `docs/adding_github_model_stage3.md` в формате:
  - Quick Start для новичков
  - Template Section для подключения любой модели из GitHub
- Добавлены `examples/` для запуска fake-модели без написания кода

## Для пользователей без опыта

- Начните с `docs/adding_github_model_stage3.md` (раздел Quick Start)
- Запустите fake-модель через `examples/run_fake_model.ps1` или `examples/run_fake_model.sh`
- Для реального Snowflake запускайте `examples/run_snowflake_model.ps1` (или `.sh`)
- Если локальный Python не собирает CUDA-расширения, используйте Docker-вариант:
  `examples/run_snowflake_model_docker.ps1` (или `.sh`)
- Проверяйте работоспособность через `tests/test_stage3_worker_scaffold.py`

## Tests vs Examples

- `tests/` — автотесты для CI и технической проверки.
- `examples/` — пошаговые учебные сценарии для пользователей.

## Где хранить реальные модели

- Репозитории моделей (скачанные с GitHub) храните в `external_models/` (папка в `.gitignore`).
- Рабочие обертки под PCPP кладите в `workers/<task_type>/<model_name>/`.
- Папки `workers/completion`, `workers/segmentation`, `workers/meshing` по умолчанию игнорируются git, чтобы в репозиторий не попадали тяжелые модели/веса.

## Файлы зависимостей

- `orchestrator/requirements.txt` — зависимости runtime оркестратора
- `tests/requirements.txt` — зависимости для тестов
- `requirements-dev.txt` — локальные dev-зависимости