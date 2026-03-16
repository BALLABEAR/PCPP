# Point Cloud Processing Platform (PCPP)

Модульная платформа для обработки облаков точек с кастомными пайплайнами.

## Быстрый старт

### Требования
- Docker Desktop
- Python 3.11+
- Git

### Запуск инфраструктуры

```bash
# 1. Клонировать репозиторий
git clone <repo_url>
cd pcpp

# 2. Создать .env из примера
cp .env.example .env
# Отредактировать .env при необходимости

# 3. Поднять сервисы
docker compose up -d

# 4. Проверить что всё запустилось
docker compose ps
```

### Проверка готовности (тесты)

```bash
# Установить зависимости для тестов
pip install -r tests/requirements.txt

# Запустить тесты инфраструктуры
pytest tests/test_infrastructure.py -v
```

Все тесты должны быть зелёными.

### Доступ к сервисам

| Сервис     | Адрес                  | Логин/Пароль                    |
|------------|------------------------|---------------------------------|
| MinIO UI   | http://localhost:9001  | pcpp_minio / pcpp_minio_secret  |
| PostgreSQL | localhost:5432         | pcpp_user / pcpp_password       |
| Redis      | localhost:6379         | —                               |

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
├── tests/
│   ├── requirements.txt
│   └── test_infrastructure.py      # тесты этапа 1
└── ...                             # остальное появится в следующих этапах
```

---

## Этапы разработки

### Фаза 1
- [x] **Этап 1** — Инфраструктура: PostgreSQL, Redis, MinIO
- [ ] **Этап 2** — FastAPI + Prefect + тестовый воркер
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