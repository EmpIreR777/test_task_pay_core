import asyncio
import logging
import random
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.core.config import settings
from src.core.exceptions import PaymentNotFoundError, WebhookError
from src.integrations.webhook import send_webhook
from src.models.payment import PaymentStatus
from src.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

EVENT_SUCCEEDED = 'payment.succeeded'
EVENT_FAILED = 'payment.failed'


class PaymentProcessingService:
    """Обработка одного платежа: эмуляция шлюза, обновление БД, вебхук.

    Вебхук — отдельная ответственность. Если доставка вебхука не удаётся после
    всех ретраев, сообщение НЕ уходит в DLQ: платёж уже обновлён в БД, и
    повторная обработка сообщения не имеет смысла (идемпотентная проверка выше).
    Ошибка вебхука логируется, но не кидается наружу.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def process(self, message: dict[str, Any]) -> None:
        payment_id = UUID(str(message['payment_id']))
        payment = await self._uow.payments.get_by_id(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f'Платёж {payment_id} не найден')
        if payment.status.is_terminal:
            logger.info('Платёж %s уже в %s, пропускаем', payment_id, payment.status.value)
            return

        await self._uow.commit()

        logger.info('Начинаем обработку платежа %s', payment_id)

        await asyncio.sleep(random.uniform(2, 5))  # noqa: S311
        success = random.random() < 0.9  # noqa: S311
        status = PaymentStatus.SUCCEEDED if success else PaymentStatus.FAILED

        logger.info('Платёж %s → %s', payment_id, status.value)

        processed_at = datetime.now(UTC)
        changed = await self._uow.payments.transition_status(payment_id, status, processed_at=processed_at)
        await self._uow.commit()
        if not changed:
            logger.info('Платёж %s уже обработан другим воркером, вебхук не отправляем', payment_id)
            return

        # Вебхук: ретраи внутри, но провал не роняет сообщение
        webhook_url = payment.webhook_url
        if webhook_url:
            try:
                await self._send_webhook_with_retry(
                    webhook_url=webhook_url,
                    payment_id=str(payment_id),
                    status=status.value,
                    amount=payment.amount,
                    currency=payment.currency,
                    processed_at=processed_at,
                )
                await self._uow.payments.mark_webhook_delivered(payment_id)
                await self._uow.commit()
            except WebhookError:
                logger.error(
                    'Webhook для платежа %s не доставлен после %d попыток, но платёж уже обновлён в БД',
                    payment_id,
                    settings.WEBHOOK_MAX_RETRIES,
                )

    async def _send_webhook_with_retry(
        self,
        webhook_url: str,
        payment_id: str,
        status: str,
        amount: Decimal,
        currency: str,
        processed_at: datetime,
    ) -> None:
        max_retries = settings.WEBHOOK_MAX_RETRIES
        timeout = settings.WEBHOOK_TIMEOUT
        last_error: str | None = None

        for attempt in range(1, max_retries + 1):
            try:
                await send_webhook(
                    url=webhook_url,
                    payment_id=payment_id,
                    status=status,
                    amount=amount,
                    currency=currency,
                    event=EVENT_SUCCEEDED if status == PaymentStatus.SUCCEEDED.value else EVENT_FAILED,
                    processed_at=processed_at,
                    timeout=timeout,
                )
                logger.info('Webhook для платежа %s отправлен (попытка %d)', payment_id, attempt)
                return
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    'Ошибка webhook для %s (попытка %d/%d): %s',
                    payment_id,
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise WebhookError(f'Webhook не доставлен после {max_retries} попыток: {last_error}')
