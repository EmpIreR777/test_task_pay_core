import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, Numeric, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.constants import (
    AMOUNT_PRECISION,
    AMOUNT_SCALE,
    MAX_DESCRIPTION_LENGTH,
    MAX_EVENT_TYPE_LENGTH,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MAX_WEBHOOK_URL_LENGTH,
)
from src.models.base import Base, CreatedMixin, TimestampMixin


class PaymentStatus(StrEnum):
    """Статусы платежа."""

    PENDING = 'pending'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'

    @property
    def is_terminal(self) -> bool:
        return self in (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED)


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    """Значения членов enum — именно они лежат в БД."""
    return [str(member.value) for member in enum_cls]


class Payment(Base, TimestampMixin):
    """Модель платежа."""

    __tablename__ = 'payments'
    __table_args__ = (
        Index('ix_payments_status', 'status'),
        Index('ix_payments_created_at', 'created_at'),
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=AMOUNT_PRECISION, scale=AMOUNT_SCALE),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(String(MAX_DESCRIPTION_LENGTH), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column('metadata', JSONB, nullable=False, default=dict)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(
            PaymentStatus,
            native_enum=False,
            create_constraint=False,
            values_callable=_enum_values,
            name='paymentstatus',
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(MAX_IDEMPOTENCY_KEY_LENGTH),
        unique=True,
        nullable=False,
        index=True,
    )
    webhook_url: Mapped[str] = mapped_column(String(MAX_WEBHOOK_URL_LENGTH), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Факт доставки уведомления отделён от факта обработки платежа.
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Outbox(Base, CreatedMixin):
    """Outbox таблица для гарантированной доставки событий."""

    __tablename__ = 'outbox'
    __table_args__ = (
        Index(
            'ix_outbox_unprocessed',
            'created_at',
            postgresql_where=text('processed_at IS NULL AND failed_at IS NULL'),
        ),
        Index('ix_outbox_payment_id', 'payment_id'),
    )

    event_type: Mapped[str] = mapped_column(String(MAX_EVENT_TYPE_LENGTH), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
