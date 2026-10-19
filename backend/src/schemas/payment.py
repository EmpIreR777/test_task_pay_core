from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from src.core.constants import AMOUNT_PRECISION, AMOUNT_SCALE, MAX_DESCRIPTION_LENGTH


class CurrencyEnum(StrEnum):
    """Допустимые валюты."""

    RUB = 'RUB'
    USD = 'USD'
    EUR = 'EUR'


class PaymentCreateRequest(BaseModel):
    """Запрос на создание платежа."""

    amount: Decimal = Field(max_digits=AMOUNT_PRECISION, decimal_places=AMOUNT_SCALE)
    currency: CurrencyEnum
    description: str | None = Field(None, max_length=MAX_DESCRIPTION_LENGTH)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

    @field_validator('amount')
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError('Сумма должна быть больше нуля')
        return v


class PaymentResponse(BaseModel):
    """Ответ при создании платежа (202 Accepted)."""

    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID
    status: str
    created_at: datetime


class PaymentDetailResponse(BaseModel):
    """Детальная информация о платеже."""

    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID
    amount: Decimal
    currency: str
    description: str | None
    metadata: dict[str, Any]
    status: str
    idempotency_key: str
    webhook_url: str | None
    created_at: datetime
    processed_at: datetime | None
    webhook_delivered_at: datetime | None
    failure_reason: str | None
