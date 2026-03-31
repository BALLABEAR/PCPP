# Единый гайд: как добавить новую модель и новый пайплайн

Этот документ написан для человека без глубокого опыта программирования.
Идея простая: делаем шаги по порядку и проверяем результат командами.

## 0) Что нужно заранее

- Установлен Docker Desktop.
- Репозиторий уже скачан.
- Открыт терминал в корне проекта `PCPP`.

Запуск системы:

```bash
docker compose up -d --build
```

Проверка, что API живой:

```bash
curl http://localhost:8000/health
```

Ожидаемо: `{"status":"ok"}`.

---

## 1) Добавляем новую модель (нейросеть)

### Шаг 1. Сгенерировать каркас модели

Пример для модели восстановления облака точек:

```bash
python workers/base/create_model_adapter.py \
  --task-type completion \
  --model-id my_completion_model \
  --repo-path https://github.com/your-org/your-model \
  --entry-command "python run.py --config config.yaml" \
  --input-format .xyz,.ply \
  --output-format .xyz
```

После этого появится папка:

`workers/completion/my_completion_model/`

Внутри будут готовые файлы:

- `worker.py`
- `model_card.yaml`
- `runtime.manifest.yaml`
- `Dockerfile`
- `README.generated.md`

### Шаг 2. Подключить реальный запуск модели

Откройте `worker.py` и замените шаблонный passthrough на реальный вызов вашей нейросети.

Что важно в `worker.py`:

- принимает `--input`;
- пишет результат в `--output-dir`;
- возвращает путь к выходному файлу.

### Шаг 3. Описать зависимости

Заполните `runtime.manifest.yaml`:

- `system_packages` - Linux-пакеты через apt;
- `python.pip` / `python.pip_commands` - Python-зависимости;
- `build_steps` - сборка extension (если нужна).

Установка выполняется автоматически через `install_from_manifest.py` во время сборки Docker-образа.

### Шаг 4. Проверить `model_card.yaml`

Проверьте, что в карточке модели есть форматы:

- `accepted_input_formats`
- `produced_output_formats`
- `preferred_output_format`

Это нужно для автоматической проверки совместимости шагов в пайплайне.

### Шаг 5. Проверить модель

Проверка через Docker-скрипт:

Windows:

```powershell
./examples/run_model_docker.ps1 -TaskType completion -ModelId my_completion_model -InputPath ./examples/model_inputs/input.ply
```

Linux/macOS:

```bash
bash ./examples/run_model_docker.sh completion my_completion_model ./examples/model_inputs/input.ply
```

Если это именно PoinTr, можно использовать готовые скрипты:

Windows:

```powershell
./examples/run_pointr_model_docker.ps1 -InputPath ./examples/model_inputs/input.xyz -WeightsPath ./external_models/PoinTr/pretrained/PoinTr_PCN.pth
```

Linux/macOS:

```bash
bash ./examples/run_pointr_model_docker.sh ./examples/model_inputs/input.xyz ./external_models/PoinTr/pretrained/PoinTr_PCN.pth
```

### Шаг 6. Убедиться, что модель видна в реестре

```bash
curl http://localhost:8000/registry/models
```

В ответе должен быть `id: my_completion_model`.

---

## 2) Добавляем новый пайплайн

Сейчас для нового пайплайна нужно сделать только 2 вещи.

### Шаг 1. Создать файл flow

Создайте файл, например:

`flows/stage4_my_new_flow.py`

Логика: какие шаги идут по очереди и какие параметры принимает flow.

### Шаг 2. Добавить одну запись в `flow_definitions.py`

Откройте `flows/flow_definitions.py` и добавьте `FlowDefinition`:

- `flow_id` - уникальный id;
- `flow_callable_path` - путь к функции flow;
- `step_builder_path` - если хотите авто-валидацию форматов по шагам;
- `template` - чтобы пайплайн появился во фронтенде в списке.

Пример `flow_callable_path`:

`"flows.stage4_my_new_flow:stage4_my_new_flow"`

После этого вручную обновлять `flows_registry`, `tasks`, `pipelines`, `flow_validation` не нужно.

### Шаг 3. Проверить, что пайплайн появился

```bash
curl http://localhost:8000/pipelines/templates
```

В ответе должен появиться ваш `flow_id`.

### Шаг 4. Проверить запуск пайплайна

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "input_bucket": "pcpp-files",
    "input_key": "uploads/example.xyz",
    "flow_id": "stage4_my_new_flow",
    "flow_params": {}
  }'
```

Скопируйте `id` задачи и проверьте статус:

```bash
curl http://localhost:8000/tasks/<TASK_ID>
```

---

## 3) Как проверить через frontend

1. Откройте `http://localhost:3000`.
2. Загрузите файл.
3. Выберите пайплайн (из `/pipelines/templates`).
4. Нажмите Run.
5. Дождитесь `completed`.
6. Нажмите Download Result.

---

## 4) Мастер добавления модели (Wizard)

Во frontend добавлен MVP-мастер `Model Onboarding Wizard` (ниже блока `Model Catalog`).
Он выполняет шаги:

1. `validate` - проверка входных полей и путей.
2. `scaffold` - генерация/обновление каркаса адаптера.
3. `build` - сборка Docker-образа модели.
4. `smoke` - пробный запуск на тестовом входе.

### Backend endpoint-ы мастера

- `POST /onboarding/models/validate`
- `POST /onboarding/models/scaffold`
- `POST /onboarding/models/build`
- `POST /onboarding/models/smoke-run`
- `GET /onboarding/models/runs/{id}`

### Что делать при ошибке в Wizard

- Нажмите `Show logs` (в MVP это блок логов под кнопкой).
- Проверьте секцию `Что исправить` (ошибка классифицируется автоматически).
- Исправьте проблему и повторите шаг кнопкой `Retry`.

---

## 5) Частые проблемы и быстрые решения

### Модель не видна в `/registry/models`

- Проверьте, что у модели есть `model_card.yaml` с полем `id`.
- Перезапустите orchestrator:

```bash
docker compose up -d --build orchestrator
```

### Новый пайплайн не появляется в `/pipelines/templates`

- Проверьте, что добавлен `template` в `flows/flow_definitions.py`.
- Проверьте синтаксис `flow_callable_path`.
- Перезапустите orchestrator.

### Ошибка зависимостей при сборке модели

- Исправьте `runtime.manifest.yaml` (пакеты и команды установки).
- Повторите запуск Docker-скрипта.

### Ошибка `size mismatch` или `is not in the models registry`

- Обычно это несовместимость `weights` и `config`.
- Выберите config той же архитектуры, что и checkpoint (например `AdaPoinTr` c `AdaPoinTr.yaml`).

### Ошибка `No module named ...` (например `emd`, `pointnet2_ops`)

- Добавьте сборку extension в `runtime.manifest.yaml` в блок `build_steps`.
- Пересоберите модельный образ (`--no-cache` при необходимости).

### Ошибка `Failed to initialize NumPy` / `_ARRAY_API not found`

- Зафиксируйте `numpy<2` в `runtime.manifest.yaml`.
- Пересоберите образ.

### Ошибка `failed to connect to the docker API`

- Запустите Docker Desktop.
- Убедитесь, что активен Linux engine.

### Форматная несовместимость шагов

- Проверьте в `model_card.yaml`:
  - `accepted_input_formats`
  - `produced_output_formats`
  - `preferred_output_format`

---

## 6) Чеклист "Готово"

- [ ] Модель собирается и запускается через Docker-скрипт.
- [ ] Модель видна в `GET /registry/models`.
- [ ] Новый пайплайн виден в `GET /pipelines/templates`.
- [ ] Задача с новым `flow_id` запускается через `POST /tasks`.
- [ ] Пайплайн отрабатывает и дает скачиваемый результат во frontend.
