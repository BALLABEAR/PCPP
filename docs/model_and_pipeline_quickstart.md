# Гайд: добавить модель и собрать пайплайн

## 1) Поднять систему

В корне проекта:

```bash
docker compose up -d --build
```

Проверка API:

```bash
curl http://localhost:8000/health
```

Откройте frontend: `http://localhost:3000`.

---

## 2) Добавить модель (вкладка `Добавить модель`)

### Что заполнить обязательно

- `Task type` (например `completion`, `meshing` или свой);
- `Model id` (lower_snake_case, например `my_model`);
- `Repo path` (путь к коду модели);
- `Weights path` и `Config path`;
- тип входа/выхода (`point_cloud` или `mesh`).

### Advanced-поля

По умолчанию можно оставить пустыми.  
Если сборка/запуск падают, дополняйте:

- `entry_command`
- `extra_pip_packages`
- `pip_requirements_files`
- `pip_extra_args`
- `system_packages`
- `base_image`
- `extra_build_steps`
- `env_overrides`
- `smoke_args`

### Запуск мастера

Нажмите `Добавить модель`.  
Мастер выполнит шаги: `validate -> scaffold -> build -> smoke -> registry`.

Успешный результат:

- модель появилась в каталоге;
- в API `GET /registry/models` у модели `ready: true`.

---

## 3) Собрать пайплайн (вкладка `Добавить пайплайн`)

1. Укажите `Pipeline name`.
2. Добавьте шаги (модели) по порядку.
3. Для каждого шага при необходимости задайте `params` в формате `KEY=VALUE` (по строкам).
4. Нажмите `Проверить пайплайн`.
5. Если валидация успешна — `Сохранить пайплайн`.

После сохранения пайплайн появляется в `Запустить пайплайн`.

---

## 4) Запустить пайплайн

Во вкладке `Запустить пайплайн`:

1. загрузите входной файл;
2. выберите сохраненный pipeline template;
3. нажмите `Upload and Run`.

После статуса `completed` доступна ссылка `Download result`.

# Короткий гайд: добавить модель и собрать пайплайн

Этот документ про текущий рабочий процесс через frontend.

## 1) Поднять систему

В корне проекта:

```bash
docker compose up -d --build
```

Проверка API:

```bash
curl http://localhost:8000/health
```

Откройте frontend: `http://localhost:3000`.

---

## 2) Добавить модель (вкладка `Добавить модель`)

### Что заполнить обязательно

- `Task type` (например `completion`, `meshing` или свой);
- `Model id` (lower_snake_case, например `my_model`);
- `Repo path` (путь к коду модели);
- `Weights path` и `Config path`;
- тип входа/выхода (`point_cloud` или `mesh`).

### Advanced-поля

По умолчанию можно оставить пустыми.  
Если сборка/запуск падают, дополняйте:

- `entry_command`
- `extra_pip_packages`
- `pip_requirements_files`
- `pip_extra_args`
- `system_packages`
- `base_image`
- `extra_build_steps`
- `env_overrides`
- `smoke_args`

### Запуск мастера

Нажмите `Добавить модель`.  
Мастер выполнит шаги: `validate -> scaffold -> build -> smoke -> registry`.

Успешный результат:

- модель появилась в каталоге;
- в API `GET /registry/models` у модели `ready: true`.

---

## 3) Собрать пайплайн (вкладка `Добавить пайплайн`)

1. Укажите `Pipeline name`.
2. Добавьте шаги (модели) по порядку.
3. Для каждого шага при необходимости задайте `params` в формате `KEY=VALUE` (по строкам).
4. Нажмите `Проверить пайплайн`.
5. Если валидация успешна — `Сохранить пайплайн`.

После сохранения пайплайн появляется в `Запустить пайплайн`.

---

## 4) Запустить пайплайн

Во вкладке `Запустить пайплайн`:

1. загрузите входной файл;
2. выберите сохраненный pipeline template;
3. нажмите `Upload and Run`.

После статуса `completed` доступна ссылка `Download result`.
