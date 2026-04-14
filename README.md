# Point Cloud Processing Platform (PCPP)

Платформа для обработки облаков точек с web-интерфейсом, API-оркестратором и Docker-адаптерами моделей.

## Что умеет

- добавление моделей через мастер во frontend;
- сборка пользовательских пайплайнов из добавленных моделей;
- запуск задач с загрузкой входного файла и скачиванием результата;
- проверка совместимости шагов по форматам;
- выполнение шагов в Docker-окружении.

## Актуальная архитектура

```text
Frontend -> FastAPI Orchestrator -> pipeline_flow -> Dockerized Workers
                                  -> MinIO (входы/результаты)
                                  -> PostgreSQL (tasks/pipelines/registry)
```

## Быстрый старт

### 1) Запуск

```bash
git clone <repo_url>
cd PCPP
cp .env.example .env
docker compose up -d --build
```

Проверка API:

```bash
curl http://localhost:8000/health
```

### 2) Интерфейсы

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- MinIO Console: `http://localhost:9001`

## Рабочий сценарий

1. Открыть frontend.
2. Во вкладке `Добавить модель` пройти мастер (`validate -> scaffold -> build -> smoke -> registry`).
3. Во вкладке `Добавить пайплайн` создать draft из готовых моделей.
4. Во вкладке `Запустить пайплайн` загрузить файл и выполнить задачу.
5. Скачать результат после статуса `completed`.

## Структура репозитория

```text
orchestrator/   # API, сервисы, модели БД, онбординг
flows/          # pipeline_flow и рантайм выполнения шагов
workers/base/   # базовый контракт воркера, конвертация, runtime-утилиты
frontend/       # UI
docs/           # документация
```

## Документация

- `docs/model_and_pipeline_quickstart.md` — короткий практический гайд по добавлению моделей и пайплайнов.
