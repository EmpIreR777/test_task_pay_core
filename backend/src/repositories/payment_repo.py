from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.payment import Outbox, Payment, PaymentStatus


class PaymentRepository:
    """Репозиторий для работы с платежами."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        amount: Decimal,
        currency: str,
        description: str | None,
        metadata: dict[str, Any],
        idempotency_key: str,
        webhook_url: str,
    ) -> Payment:
        payment = Payment(
            amount=amount,
            currency=currency,
            description=description,
            metadata_=metadata,
            idempotency_key=idempotency_key,
            webhook_url=webhook_url,
        )
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        stmt = select(Payment).where(Payment.idempotency_key == idempotency_key)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def transition_status(
        self,
        payment_id: UUID,
        status: PaymentStatus,
        processed_at: datetime | None = None,
        failure_reason: str | None = None,
    ) -> bool:
        """Атомарно перевести платёж из pending в терминальный статус."""
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.PENDING)
            .values(
                status=status,
                processed_at=processed_at or datetime.now(UTC),
                failure_reason=failure_reason,
            )
            .returning(Payment.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_webhook_delivered(self, payment_id: UUID) -> None:
        """Зафиксировать факт доставки уведомления."""
        stmt = update(Payment).where(Payment.id == payment_id).values(webhook_delivered_at=datetime.now(UTC))
        await self._session.execute(stmt)

    async def set_failure_reason(self, payment_id: UUID, reason: str) -> None:
        """Сохранить причину сбоя обработки (платёж при этом остаётся pending)."""
        stmt = update(Payment).where(Payment.id == payment_id).values(failure_reason=reason[:2000])
        await self._session.execute(stmt)


class OutboxRepository:
    """Репозиторий для работы с outbox."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        event_type: str,
        payload: dict[str, Any],
        payment_id: UUID | None = None,
    ) -> Outbox:
        outbox = Outbox(event_type=event_type, payload=payload, payment_id=payment_id)
        self._session.add(outbox)
        await self._session.flush()
        return outbox

    async def get_unprocessed(self, limit: int = 100) -> list[Outbox]:
        """События, которые ещё не опубликованы и не исчерпали лимит ретраев."""
        stmt = (
            select(Outbox)
            .where(Outbox.processed_at.is_(None), Outbox.failed_at.is_(None))
            .order_by(Outbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_publish_failure(self, event_id: UUID, error: str, max_retries: int) -> int:
        """Зафиксировать неудачную публикацию события и вернуть счётчик ретраев."""
        now = datetime.now(UTC)
        stmt = (
            update(Outbox)
            .where(Outbox.id == event_id, Outbox.processed_at.is_(None))
            .values(
                retry_count=Outbox.retry_count + 1,
                last_error=error[:2000],
                failed_at=case(
                    (Outbox.retry_count + 1 >= max_retries, now),
                    else_=Outbox.failed_at,
                ),
            )
            .returning(Outbox.retry_count)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() or 0
