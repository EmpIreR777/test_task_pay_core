from http import HTTPStatus


class AppError(Exception):
    """Базовое доменное исключение: глобальный handler переводит его в HTTP-ответ.

    Статус и текст задаются наследником, поэтому роутерам не нужен try/except —
    они просто пробрасывают исключение сервиса наружу.
    """

    status_code: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message: str = 'Внутренняя ошибка сервера'

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


# ==================== Payment Exceptions ====================


class PaymentNotFoundError(AppError):
    """Платёж не найден."""

    status_code = HTTPStatus.NOT_FOUND
    default_message = 'Платёж не найден'


class IdempotencyConflictError(AppError):
    """Idempotency-Key уже использован с другим телом запроса."""

    status_code = HTTPStatus.CONFLICT
    default_message = 'Idempotency-Key уже использован с другим телом запроса'


# ==================== External Service Exceptions ====================


class WebhookError(AppError):
    """Ошибка отправки webhook."""

    status_code = HTTPStatus.BAD_GATEWAY
    default_message = 'Ошибка отправки webhook'
