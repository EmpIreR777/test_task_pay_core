import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from src.core.config import settings

# Контекст текущей обработки. Изолирован в async-задачах,
# поэтому разные задачи не перетирают поля друг друга.
# default=None, т.к. мутабельный default {} был бы общим для всех контекстов.
_log_context: ContextVar[dict[str, Any] | None] = ContextVar('log_context', default=None)


def bind_context(**fields: Any) -> None:
    """Добавить поля контекста (payment_id, request_id) в текущий async-контекст."""
    _log_context.set({**(_log_context.get() or {}), **fields})


def clear_context() -> None:
    """Сбросить контекст перед обработкой новой задачи."""
    _log_context.set(None)


class JSONFormatter(logging.Formatter):
    """Сериализует запись лога вместе с контекстом из contextvars в одну JSON-строку."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'location': f'{record.module}:{record.lineno}',
            'message': record.getMessage(),
        }
        payload.update(_log_context.get() or {})
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """Настроить корневой логгер: JSON в stdout, уровень из settings.LOG_LEVEL."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())

    # SQL-запросы SQLAlchemy шумят на INFO — поднимаем до WARNING, если это не DEBUG-режим.
    logging.getLogger('sqlalchemy.engine').setLevel(
        logging.DEBUG if root.level == logging.DEBUG else logging.WARNING,
    )
