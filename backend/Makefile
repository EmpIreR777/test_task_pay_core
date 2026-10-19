.PHONY: run run-consumer run-outbox sync-all alembic-rev alembic-up alembic-down pre-commit-install lint ruff mypy test test-cov clean-cache

# =====================================================
# App
# =====================================================
run:
	uv run uvicorn src.app:app --host 127.0.0.1 --port 8000 --reload

run-consumer:
	uv run faststream run src.tasks.consumer:app

run-outbox:
	uv run faststream run src.tasks.outbox_processor:app

# =====================================================
# Dependencies
# =====================================================
sync-all:
	uv sync --all-groups

# =====================================================
# Database / Alembic
# =====================================================
alembic-rev:
	./alembic_rev.sh "$(m)"

alembic-up:
	uv run alembic upgrade head

alembic-down:
	uv run alembic downgrade -1

# =====================================================
# Code Quality
# =====================================================
pre-commit-install:
	uv run pre-commit install --install-hooks

lint:
	uv run pre-commit run --all-files

ruff:
	uv run ruff check --fix && uv run ruff format .

mypy:
	uv run mypy src --cache-dir .mypy_cache

# =====================================================
# Tests
# =====================================================
# Тесты поднимают отдельную БД payment_processing_test (создаётся автоматически)
# и не трогают рабочую БД из .env.
# POSTGRES_HOST=localhost — порт 5432 проброшен из docker-compose; переменная
# окружения имеет приоритет над .env, поэтому значение backend-db из .env не мешает.
test:
	POSTGRES_HOST=$${POSTGRES_HOST:-localhost} uv run pytest -v

test-cov:
	POSTGRES_HOST=$${POSTGRES_HOST:-localhost} uv run pytest --cov=src --cov-report=term-missing --cov-report=html

# =====================================================
# Maintenance
# =====================================================
clean-cache:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
