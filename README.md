# Асинхронный сервис процессинга платежей

Микросервис приёма платежей: запрос создания возвращается сразу (`202 Accepted`),
а обработка идёт асинхронно — через RabbitMQ. Результат клиенту доставляется
webhook-уведомлением.

| | |
|---|---|
| **API** | FastAPI + Pydantic v2 |
| **БД** | PostgreSQL 16, SQLAlchemy 2.0 (async) |
| **Брокер** | RabbitMQ 3 + FastStream |
| **Миграции** | Alembic |
| **Запуск** | Docker + docker-compose |
| **Качество** | ruff, mypy (strict), pytest, pre-commit |

---

## Содержание

1. [Как это работает](#как-это-работает)
2. [Быстрый старт (Docker)](#быстрый-старт-docker)
3. [Примеры запросов](#примеры-запросов)
4. [Makefile: корневой](#makefile-корневой)
5. [Локальная разработка без Docker](#локальная-разработка-без-docker)
6. [Makefile: backend](#makefile-backend)
7. [API](#api)
8. [RabbitMQ: обменники, очереди, DLQ](#rabbitmq-обменники-очереди-dlq)
9. [Outbox pattern](#outbox-pattern)
10. [Идемпотентность](#идемпотентность)
11. [Переменные окружения](#переменные-окружения)
12. [Модель данных](#модель-данных)
13. [Тесты и качество кода](#тесты-и-качество-кода)
14. [CI](#ci)
15. [Структура проекта](#структура-проекта)
16. [Что стоит доделать для прода](#что-стоит-доделать-для-прода)

---

## Как это работает

```
POST /api/v1/payments
        │
        ▼
   ┌─────────────┐   одна транзакция: payments + outbox
   │   API       │──────────────────────────────────┐
   └─────────────┘                                  │
        │ 202 Accepted {payment_id, status, created_at}
        │                                            ▼
        │                                   ┌──────────────────┐
        │                                   │  таблица outbox  │
        │                                   └──────────────────┘
        │                                            │ опрос каждые 5с
        │                                            ▼
        │                                   ┌──────────────────┐
        │                                   │ outbox-processor │  публикует событие
        │                                   └──────────────────┘
        │                                            │
        │                                            ▼
        │                              exchange `payments` (topic)
        │                              routing key `payment.created`
        │                                            │
        │                                            ▼
        │                                   ┌──────────────────┐
        │                                   │ очередь          │
        │                                   │ `payments.new`   │
        │                                   └──────────────────┘
        │                                            │
        │                                            ▼
        │                                   ┌──────────────────┐
        │                                   │    consumer      │  3 попытки, backoff 1s/2s
        │                                   │  эмуляция шлюза  │  2–5 с, 90% успех
        │                                   └──────────────────┘
        │                                       │          │
        │                       обновление статуса │       │ 3 ошибки подряд
       │                       в БД (succeeded/    │       ▼
        │                       failed)            ┌────────────────┐
        │                                       │  │ payments.dlq   │  Dead Letter Queue
        │                                       │  └────────────────┘
        │                                       ▼
        └──────────────────────────────►  webhook POST на webhook_url
                                          (3 попытки, backoff 1s/2s)
```

Ключевая идея: **API никогда не ждёт обработку**. Он атомарно пишет платёж и
событие в outbox, отвечает `202`, а доставку события в брокер берёт на себя
отдельный процесс. Если брокер или БД лежат в момент записи — событие не
потеряется, а дождётся в outbox.

---

## Быстрый старт (Docker)

### 1. Требования

- Docker и docker-compose (v2)
- `make` (в macOS/Linux есть из коробки)

### 2. Скопировать переменные окружения

```bash
cp .env.example .env
```

Файл `.env.example` содержит готовые dev-значения, Docker Compose подхватывает
`.env` автоматически. Для прода ключ нужно заменить:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Поднять всё одной командой

```bash
make up
```

Команда из корня репозитория:

1. соберёт образ и поднимет `postgres`, `rabbitmq`, `migrator`, `api`,
   `consumer`, `outbox-processor`;
2. дождётся, пока `migrator` применит миграции Alembic, и покажет его логи;
3. удалит завершившийся контейнер `migrator` (он одноразовый).

Итог:

```
NAME                                  STATUS
payment_processing-api                Up
payment_processing-consumer           Up
payment_processing-db                 Up (healthy)
payment_processing-outbox-processor   Up
payment_processing-rabbitmq           Up (healthy)
```

### 4. Проверить, что всё работает

```bash
curl http://localhost:8000/health/full
# {"status":"ok","database":"ok"}
```

Liveness (`/health`) не ходит в зависимости, readiness (`/health/full`) проверяет
соединение с БД и возвращает `503 {"status":"degraded","database":"unavailable"}`
при её недоступности. Доступность RabbitMQ контролируется на уровне инфраструктуры
(healthcheck `rabbitmq-diagnostics ping` в docker-compose и `depends_on:
service_healthy` у сервисов, работающих с брокером) — приложение этой проверкой
не занимается.

| Адрес | Что |
|---|---|
| http://localhost:8000 | API |
| http://localhost:8000/docs | Swagger UI (интерактивная документация) |
| http://localhost:8000/redoc | ReDoc (то же самое в другом оформлении) |
| http://localhost:8000/openapi.json | OpenAPI-схема (machine-readable) |
| http://localhost:15672 | RabbitMQ Management (guest / guest) |
| localhost:5432 | PostgreSQL (postgres / postgres) |


### 5. Положить контейнеры

```bash
make down      # контейнеры и сеть, данные БД сохраняются
make clean     # + тома (БД и RabbitMQ очищаются полностью)
make logs      # логи всех сервисов
```

---

## Примеры запросов

Создание платежа. **Заголовок `Idempotency-Key` обязателен** (1–255 символов,
без пробелов), без него — `422`. Без `X-API-Key` — `401`.

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: dev-api-key-change-in-production-this-is-32-chars-minimum" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
        "amount": "1500.00",
        "currency": "RUB",
        "description": "Оплата заказа #42",
        "metadata": {"order_id": "42", "user_id": "u-1"},
        "webhook_url": "https://example.com/webhooks/payment"
      }'
```

Ответ `202 Accepted`:

```json
{
  "payment_id": "4311bdea-8fda-4296-a5ef-ce40200305e9",
  "status": "pending",
  "created_at": "2026-10-19T21:54:32.871457Z"
}
```

Получение платежа (через 2–5 секунд статус станет `succeeded` или `failed`):

```bash
curl http://localhost:8000/api/v1/payments/4311bdea-8fda-4296-a5ef-ce40200305e9 \
  -H "X-API-Key: dev-api-key-change-in-production-this-is-32-chars-minimum"
```

```json
{
  "payment_id": "4311bdea-8fda-4296-a5ef-ce40200305e9",
  "amount": "1500.00",
  "currency": "RUB",
  "description": "Оплата заказа #42",
  "metadata": {"order_id": "42", "user_id": "u-1"},
  "status": "succeeded",
  "idempotency_key": "7BAD4420-D65C-4541-AA7B-6271048E987D",
  "webhook_url": "https://example.com/webhooks/payment",
  "created_at": "2026-10-19T21:54:32.871457Z",
  "processed_at": "2026-10-19T21:54:37.082763Z",
  "webhook_delivered_at": "2026-10-19T21:54:37.283441Z",
  "failure_reason": null
}
```

`webhook_delivered_at` заполняется только после успешной отправки уведомления —
по нему видно, что платёж обработан, а доставка ещё не подтверждена (или не
удалась вовсе).

Тот же запрос с тем же `Idempotency-Key` вернёт **тот же** `payment_id` и не
создаст второй платёж. Если тем же ключом прислать запрос с **другим** телом —
`409 Conflict`: молчаливый возврат старого платежа скрыл бы от клиента, что его
новый платёж не создан.

### Посмотреть, что происходит внутри

```bash
# События outbox
docker compose exec backend-db psql -U postgres -d payment_processing \
  -c "SELECT event_type, processed_at, retry_count, last_error FROM outbox;"

# Очереди RabbitMQ
docker compose exec rabbitmq rabbitmqctl list_queues name messages

# Логи consumer'а
docker compose logs -f consumer
```

Логи пишутся в JSON, в каждую запись подставляется `payment_id` из
контекста задачи:

```json
{"timestamp": "2026-10-19T21:50:37.988326+00:00", "level": "INFO",
 "logger": "src.integrations.rabbitmq.consumer", "location": "consumer:36",
 "message": "Платёж 98f2f233... обработан (попытка 1)",
 "payment_id": "98f2f233-7437-4d9c-9769-b79cf68096e3"}
```

---

## Makefile: корневой

Команды выполняются из корня репозитория.

| Команда | Что делает |
|---|---|
| `make up` | Собрать и поднять всё, показать логи миграций, убрать контейнер `migrator` |
| `make migrate` | Применить миграции отдельно (`docker compose run --rm migrator`) — паттерн для CI/CD |
| `make down` | Остановить и удалить контейнеры (данные сохраняются) |
| `make clean` | Остановить всё и удалить **тома** (БД и RabbitMQ очищаются) |
| `make logs` | Логи всех сервисов |

### Про контейнер `migrator`

Это одноразовый init-контейнер: он применяет миграции и завершается с кодом `0`.
В `docker compose ps` он остаётся в состоянии `Exited (0)` — **это не ошибка**, а
признак того, что миграции прошли. Остальные сервисы стартуют только после него
(`depends_on: condition: service_completed_successfully`), поэтому схема БД всегда
готова.

Compose не умеет сам удалять завершившийся контейнер сервиса (в спецификации нет
аналога `docker run --rm`; [фича закрыта как obsolete](https://github.com/docker/compose/issues/10688)),
поэтому это делается отдельной командой — `make up` уже делает это за вас, а
`docker compose rm -f migrator` — вручную.

---

## Локальная разработка без Docker

Нужны [uv](https://docs.astral.sh/uv/) и локальные Postgres + RabbitMQ
(или запущенный стек из Docker только на инфраструктуре).

```bash
cd backend

# Зависимости
make sync-all

# Переменные окружения: backend/.env имеет приоритет над корневым .env,
# поэтому здесь хосты указываются на localhost
cp .env.example .env

# Миграции
make alembic-up

# Три процесса — в трёх терминалах
make run           # API:              http://127.0.0.1:8000
make run-consumer  # consumer:         faststream run src.tasks.consumer:app
make run-outbox    # outbox-processor: faststream run src.tasks.outbox_processor:app
```

Консоль FastStream сама обрабатывает `SIGINT`/`SIGTERM` и гасит приложение
корректно: consumer дожидается обработки сообщений «в полёте», outbox-processor
отменяет фоновый опрос.

---

## Makefile: backend

Команды выполняются из каталога `backend`.

### Запуск

| Команда | Что делает |
|---|---|
| `make run` | API в режиме reload на `127.0.0.1:8000` |
| `make run-consumer` | Consumer (FastStream) |
| `make run-outbox` | Outbox-processor (FastStream) |
| `make sync-all` | Установить зависимости (включая dev- и lint-группы) |

### Миграции

| Команда | Что делает |
|---|---|
| `make alembic-rev m="описание"` | Создать ревизию миграции |
| `make alembic-up` | Применить миграции (`upgrade head`) |
| `make alembic-down` | Откатить последнюю миграцию |

### Линтеры и тесты

| Команда | Что делает |
|---|---|
| `make test` | Прогнать тесты (pytest) |
| `make test-cov` | Тесты с отчётом покрытия (HTML в `htmlcov/`) |
| `make lint` | Все проверки pre-commit (ruff, mypy, codespell) |
| `make ruff` | ruff: автоисправление + форматирование |
| `make mypy` | mypy strict по `src/` |
| `make pre-commit-install` | Установить git-хуки |
| `make clean-cache` | Почистить кэши (`.mypy_cache`, `.pytest_cache`, `__pycache__`) |

Тесты работают в **отдельной БД** `payment_processing_test` (создаётся
автоматически при первом прогоне) и не задевают рабочую БД. Нужна только
доступность Postgres на `localhost:5432` — порт проброшен из docker-compose.

---

## API

Все эндпоинты требуют заголовок `X-API-Key`.

| Метод | Путь | Ответ |
|---|---|---|
| `POST` | `/api/v1/payments` | `202 Accepted` — `{payment_id, status, created_at}` |
| `GET` | `/api/v1/payments/{payment_id}` | `200 OK` — детальная информация |
| `GET` | `/health` | liveness, не ходит в зависимости |
| `GET` | `/health/full` | readiness: проверяет БД, `503` при недоступности |

Тело запроса создания платежа:

| Поле | Тип | Обязательность | Описание |
|---|---|---|---|
| `amount` | decimal | да | строго больше нуля |
| `currency` | enum | да | `RUB`, `USD`, `EUR` |
| `description` | string | нет | до 1000 символов |
| `metadata` | object | нет | произвольный JSON |
| `webhook_url` | url | да | куда слать результат |

Путь принимается и со слэшем, и без: `POST /api/v1/payments` и
`POST /api/v1/payments/` дают одинаковый `202` (в OpenAPI показан вариант без
слэша — как в ТЗ).

Ошибки: `401` — нет/неверный API-ключ, `404` — платёж не найден,
`409` — `Idempotency-Key` уже использован с другим телом запроса, `422` —
невалидные данные (в том числе пустой/длинный/с пробелами `Idempotency-Key`),
`500` — непредвиденная ошибка.

---

## RabbitMQ: обменники, очереди, DLQ

```
exchange `payments` (topic, durable)
    └── binding routing_key=payment.created
            └── queue `payments.new` (durable)
                    args: x-dead-letter-exchange=payments.dlx
                          x-dead-letter-routing-key=payments.dlq

exchange `payments.dlx` (direct, durable)
    └── binding routing_key=payments.dlq
            └── queue `payments.dlq` (durable)
```

| Объект | Имя | Тип | Назначение |
|---|---|---|---|
| Exchange | `payments` | topic | точка публикации событий |
| Queue | `payments.new` | classic | очередь обработки |
| Exchange | `payments.dlx` | direct | dead-letter exchange |
| Queue | `payments.dlq` | classic | очередь окончательно упавших сообщений |

Сообщения публикуются **персистентными** (`delivery_mode=2`), поэтому переживают
перезапуск брокера.

### Обработка и ретраи

Consumer делает **3 попытки** с экспоненциальной задержкой (1 с, 2 с):

```
21:55:46  Ошибка платежа (попытка 1/3)
21:55:47  Ошибка платежа (попытка 2/3)      ← +1 с
21:55:49  Ошибка платежа (попытка 3/3)      ← +2 с
21:55:49  Платёж отправлен в DLQ после 3 попыток
```

После третьей неудачи сообщение уходит в `payments.dlq` (`nack` с
`requeue=False` → RabbitMQ сам перекладывает его в dead-letter exchange).

Топологию объявляет **каждый** процесс, работающий с брокером: без
`payments.dlx` и биндинга `payments.dlq` dead-letter сообщения удалялись бы
RabbitMQ молча, без следа.

Посмотреть, что упало в DLQ:

```bash
docker compose exec rabbitmq rabbitmqctl list_queues name messages
# payments.dlq   1
```

---

## Outbox pattern

Гарантированная публикация: событие пишется **в той же транзакции**, что и
платёж.

```
BEGIN
  INSERT INTO payments  (...)
  INSERT INTO outbox    (event_type, payload, payment_id, ...)
COMMIT
```

Дальше отдельный процесс `outbox-processor` опрашивает таблицу `outbox` раз в
5 секунд и публикует неотправленные события в брокер, отмечая их
`processed_at`. Если публикация не удалась — `retry_count` растёт, а после
3 попыток событие получает `failed_at` и больше не вычитывается (иначе оно
перечитывалось бы и логировалось бесконечно).

Что это даёт:

- **нет потерь** — если RabbitMQ лежит в момент запроса, событие ждёт в БД;
- **нет дублей** — платёж и событие создаются атомарно;
- **прозрачность** — по таблице `outbox` видно, что произошло с каждым событием.

---

## Идемпотентность

Уникальный индекс на `payments.idempotency_key` + проверка перед вставкой +
обработка гонки через `IntegrityError` → `rollback` → перечитка: при
одновременных запросах с одним ключом все получают один и тот же `payment_id`
(это проверяет тест на 10 параллельных запросов).

Правила заголовка `Idempotency-Key`:

- **1–255 символов, без пробелов** — иначе `422` (за границей API, а не
  `DataError` в БД);
- то же тело запроса → `202` и **тот же** `payment_id` — ретраи безопасны;
- другое тело запроса → `409 Conflict` — молчаливый возврат старого платежа
  скрыл бы, что новый платёж не создан.

```bash
KEY=$(uuidgen)
for i in 1 2 3; do
  curl -s -X POST http://localhost:8000/api/v1/payments \
    -H "X-API-Key: dev-api-key-change-in-production-this-is-32-chars-minimum" \
    -H "Idempotency-Key: $KEY" -H "Content-Type: application/json" \
    -d '{"amount":"10.00","currency":"RUB","webhook_url":"https://example.com/hook"}'
done
# три одинаковых payment_id, в БД одна строка
```

---

## Переменные окружения

Копируются из `.env.example` в `.env` в корне репозитория. Переменные окружения
имеют приоритет над файлом `.env`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `API_KEY` | — (обязательна) | ключ для заголовка `X-API-Key` |
| `POSTGRES_HOST` | — | хост PostgreSQL |
| `POSTGRES_PORT` | — | порт PostgreSQL |
| `POSTGRES_USER` | — | пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | — | пароль PostgreSQL |
| `POSTGRES_DB` | — | имя рабочей БД |
| `TEST_POSTGRES_DB` | `payment_processing_test` | БД для тестов |
| `RABBITMQ_URL` | `amqp://guest:guest@rabbitmq:5672//` | подключение к брокеру |
| `API_PREFIX` | `/api/v1` | префикс API-роутов |
| `CORS_ORIGINS` | `http://localhost:5173` | разрешённые origin'ы |
| `WEBHOOK_TIMEOUT` | `10` | таймаут webhook-запроса, с |
| `WEBHOOK_MAX_RETRIES` | `3` | попыток доставки webhook |
| `OUTBOX_POLL_INTERVAL` | `5` | интервал опроса outbox, с |
| `OUTBOX_BATCH_SIZE` | `100` | размер батча outbox |
| `OUTBOX_MAX_RETRIES` | `3` | попыток публикации события |
| `CONSUMER_MAX_RETRIES` | `3` | попыток обработки сообщения |
| `CONSUMER_RETRY_BASE_DELAY` | `1.0` | база backoff consumer'а, с |
| `LOG_LEVEL` | `INFO` | уровень логирования |
| `TEST_MODE` | `false` | переключает приложение на тестовую БД |

---

## Модель данных

### `payments`

| Колонка | Тип | Notes |
|---|---|---|
| `id` | UUID | PK, `gen_random_uuid()` |
| `amount` | numeric(18, 2) | строго больше нуля (`CHECK`) |
| `currency` | varchar(3) | `RUB` / `USD` / `EUR` (`CHECK`) |
| `description` | varchar(1000) | nullable |
| `metadata` | jsonb | произвольный JSON |
| `status` | varchar | `pending` / `succeeded` / `failed` (`CHECK`) |
| `idempotency_key` | varchar(255) | **unique**, индекс |
| `webhook_url` | varchar(500) | NOT NULL |
| `processed_at` | timestamptz | nullable, заполняется consumer'ом |
| `webhook_delivered_at` | timestamptz | nullable, заполняется при доставке webhook |
| `failure_reason` | text | nullable, причина сбоя обработки |
| `created_at` / `updated_at` | timestamptz | |

### `outbox`

| Колонка | Тип | Notes |
|---|---|---|
| `id` | UUID | PK |
| `event_type` | varchar(100) | `payment_created` |
| `payload` | jsonb | тело события |
| `payment_id` | UUID | nullable, индекс |
| `processed_at` | timestamptz | nullable — событие опубликовано |
| `failed_at` | timestamptz | nullable — ретраи исчерпаны |
| `retry_count` | int | счётчик неудачных публикаций |
| `last_error` | text | текст последней ошибки |

Частичный индекс `ix_outbox_unprocessed` строит��ся только на необработанные
события (`WHERE processed_at IS NULL AND failed_at IS NULL`) — выборка не
сканирует историю.

---

## Тесты и качество кода

```bash
cd backend
make test        # 35 тестов
make lint        # pre-commit: ruff + mypy + codespell
```

| Файл | Что покрывает |
|---|---|
| `tests/test_payments_api.py` | API: создание, идемпотентность (включая `409` при конфликте ключа и валидацию заголовка), валидация, авторизация, получение |
| `tests/test_consumer.py` | consumer: успех, «ошибка» шлюза, идемпотентность повторной обработки, уход в DLQ после 3 попыток |
| `tests/test_outbox.py` | outbox: публикация, ретраи, терминальный статус, `FOR UPDATE SKIP LOCKED` |

Тесты изолированы: отдельная БД `payment_processing_test`, чистка таблиц до и
после каждого теста, брокер и webhook замоканы.

Линтинг: `ruff` (широкий набор правил, включая `S` — bandit и `ANN` —
аннотации), `mypy --strict`, `codespell`, `pre-commit` с conventional commits.

---

## CI

`.github/workflows/ci.yml` — GitHub Actions. Запускается на push в `main`, на
каждом pull request и вручную; новый пуш отменяет предыдущий прогон.

| Джоб | Что проверяет |
|---|---|
| `lint` | `ruff check`, `ruff format --check`, `mypy src` |
| `test` | `pytest` на PostgreSQL 16 (поднимается сервисом в самом workflow) |
| `docker` | сборка образа (`context: backend`) |

Тесты в CI идут в отдельную БД `payment_processing_test` и **не требуют `.env`**:
все переменные окружения передаются через `env:` в шаге, а не читаются из файла.
Поэтому прогон воспроизводим на любой машине и в любом PR.

Те же проверки локально:

```bash
cd backend
make lint
make test
```

Статус прогона — во вкладке **Actions** репозитория, рядом с коммитом.

---

## Структура проекта

```
.
├── Makefile                 # up / migrate / down / clean / logs
├── docker-compose.yml       # postgres, rabbitmq, migrator, api, consumer, outbox-processor
├── .env.example
├── .github/workflows/ci.yml # CI: lint / test / docker
└── backend/
    ├── Makefile             # run / test / lint / миграции
    ├── alembic/             # миграции
    ├── alembic_rev.sh
    ├── entrypoint.sh
    ├── pyproject.toml       # зависимости, ruff, mypy, pytest
    ├── src/
    │   ├── app.py           # FastAPI-приложение
    │   ├── run_migrations.py
    │   ├── core/            # config, db, logging, security, exceptions
    │   ├── models/          # SQLAlchemy-модели
    │   ├── schemas/         # Pydantic-схемы
    │   ├── repositories/    # репозитории + Unit of Work
    │   ├── services/        # бизнес-логика
    │   ├── integrations/
    │   │   ├── rabbitmq/    # broker, publisher, consumer, topology
    │   │   └── webhook.py
    │   ├── routers/         # v1/payments, health
    │   └── tasks/           # точки входа: consumer, outbox-processor
    └── tests/
```

Слои: `routers → services → repositories → models`. Сервисы не знают про
FastAPI и RabbitMQ, интеграции не знают про бизнес-логику. Unit of Work
скрывает транзакции, HTTP-слой не трогает ORM напрямую.

---

## Что стоит доделать для прода

Задание закрыто, но для реальной эксплуатации нужно ещё. Ниже — по приоритету:
что именно ломается и почему.

### 1. Доставка webhook после финальной неудачи

Вебхук ретраится 3 раза с экспоненциальным бэкоффом, но после финальной неудачи
уведомление теряется навсегда — остаётся только лог и
`webhook_delivered_at = NULL` (по нему видно, что доставки не было, но
автоматического досылания нет). Платёж уже в терминальном статусе, DLQ-реплей
сообщения вебхук не досылает. Нужен отдельный цикл досылки: задача на отправку
в outbox с ретраями и/или admin-эндпоинт для ручной повторной отправки.

### 2. Семантика DLQ-реплея

При окончательном падении обработки (3 неудачные попытки) платёж переводится в
`failed`, а сообщение уходит в DLQ. Реплей такого сообщения ничего не делает —
consumer видит терминальный статус и подтверждает его без изменений. То есть
DLQ работает как аудиторская очередь. Для «живого» повтора нужен admin-флоу:
сбросить платёж в `pending` и переопубликовать событие.

### 3. Подпись webhook и SSRF

- Уведомление приходит на `webhook_url` без проверки подлинности — клиент не
  может отличить настоящее от подделки. Нужна HMAC-подпись в заголовке и проверка
  на стороне клиента.
- `webhook_url` принимается без ограничений: платёж может увести запрос
  consumer'а во внутреннюю сеть (`169.254.169.254`, `localhost`, `10.0.0.0/8`…).
  Нужен allowlist схем/хостов или блокировка приватных диапазонов.

### 4. Наблюдаемость

Есть структурные JSON-логи с контекстом, но нет метрик. Минимально нужны:
глубина `payments.new`, глубина `payments.dlq` (с алертом — непустая DLQ всегда
означает потерянные платежи), количество событий в `outbox` с
`failed_at IS NOT NULL` (событие, которое так и не ушло в брокер), latency
обработки и доля ошибок webhook (`webhook_delivered_at IS NULL` у платежей в
терминальном статусе).

### 5. Интеграционные тесты брокера

Топология, биндинги и DLQ проверяются только на уровне юнит-тестов с моками —
реального RabbitMQ в тестах нет. Гонки (двойной ack, пропавший биндинг,
dead-letter без консьюмера DLQ) увидит только прод. Лечится testcontainers или
smoke-тестом с реальным брокером в CI.

### 6. Эксплуатация и безопасность

- подключение к БД идёт суперпользователем — нужен отдельный пользователь
  с минимальными правами (только схема сервиса);
- нет rate limiting и ротации API-ключа — ключ один и бессрочный;
- backoff без jitter: при нескольких consumer'ах повторы синхронизируются
  волной и бьют по шлюзу одновременно.

### 7. Обслуживание данных

- нет retention для `outbox`: обработанные события копятся бесконечно —
  нужен cron/таск чистки;
- `outbox.payment_id` без внешнего ключа на `payments.id` — для outbox-паттерна
  допустимо (FK добавил бы запись в момент публикации), но ссылочной
  целостности нет.
