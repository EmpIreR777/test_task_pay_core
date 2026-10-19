FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /backend

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /backend

COPY --from=builder /usr/local /usr/local
COPY --from=builder /bin/uv /bin/uv
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini .
COPY entrypoint.sh .

RUN useradd --create-home --uid 10001 appuser \
    && chmod +x /backend/entrypoint.sh \
    && chown -R appuser:appuser /backend

USER appuser

ENTRYPOINT ["/backend/entrypoint.sh"]
