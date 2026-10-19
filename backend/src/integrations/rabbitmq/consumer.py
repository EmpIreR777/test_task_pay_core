import asyncio
import logging
from typing import Any
from uuid import UUID

from faststream.rabbit import RabbitMessage

from src.core import db
from src.core.config import settings
from src.core.exceptions import PaymentNotFoundError
from src.core.logging import bind_context, clear_context
from src.integrations.rabbitmq.broker import EXCHANGE_PAYMENTS_OBJ, QUEUE_PAYMENTS_NEW, broker
from src.models.payment import PaymentStatus
from src.repositories.unit_of_work import UnitOfWork
from src.services.payment_processing import PaymentProcessingService

logger = logging.getLogger(__name__)


@broker.subscriber(queue=QUEUE_PAYMENTS_NEW, exchange=EXCHANGE_PAYMENTS_OBJ)
async def process_payment(message: dict[str, Any], msg: RabbitMessage) -> None:
    """Один consumer: 3 попытки с экспоненциальным бэкоффом, затем DLQ.

    Транспортный слой: только RabbitMQ. Бизнес-логика — в PaymentProcessingService.
    """
    max_retries = settings.CONSUMER_MAX_RETRIES
    base_delay = settings.CONSUMER_RETRY_BASE_DELAY
    payment_id = str(message.get('payment_id', 'unknown'))

    clear_context()
    bind_context(payment_id=payment_id)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with db.async_session_factory() as session:
                uow = UnitOfWork(session)
                service = PaymentProcessingService(uow)
                await service.process(message)
            logger.info('Платёж %s обработан (попытка %d)', payment_id, attempt)
            return
        except PaymentNotFoundError as exc:
            last_error = exc
            logger.error('Платёж %s не найден, повтор бессмысленен: %s', payment_id, exc)
            break
        except Exception as exc:
            last_error = exc
            logger.warning(
                'Ошибка обработки платежа %s (попытка %d/%d): %s',
                payment_id,
                attempt,
                max_retries,
                exc,
            )
            if attempt == max_retries:
                break
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))

    await _mark_failed(payment_id, last_error)
    logger.error('Платёж %s отправлен в DLQ после %d попыток', payment_id, max_retries)
    await msg.nack(requeue=False)


async def _mark_failed(payment_id: str, error: Exception | None) -> None:
    """Перевести платёж в failed, чтобы он не остался в pending навсегда."""
    reason = f'Обработка не завершена: {error}' if error else 'Обработка не завершена'
    try:
        async with db.async_session_factory() as session:
            uow = UnitOfWork(session)
            changed = await uow.payments.transition_status(
                UUID(payment_id),
                PaymentStatus.FAILED,
                failure_reason=reason,
            )
            if not changed:
                await uow.payments.set_failure_reason(UUID(payment_id), reason)
            await uow.commit()
    except Exception:
        logger.exception('Не удалось зафиксировать причину сбоя платежа %s', payment_id)
