import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import IdempotencyConflictError, PaymentNotFoundError
from src.repositories.unit_of_work import UnitOfWork
from src.schemas.payment import PaymentCreateRequest, PaymentDetailResponse, PaymentResponse

if TYPE_CHECKING:
    from src.models.payment import Payment

logger = logging.getLogger(__name__)

EVENT_PAYMENT_CREATED = 'payment_created'


class PaymentService:
    """Сервис платежей: бизнес-логика создания и получения."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def create_payment(self, payload: PaymentCreateRequest, idempotency_key: str) -> PaymentResponse:
        """Создать платёж с проверкой идемпотентности."""
        existing = await self._uow.payments.get_by_idempotency_key(idempotency_key)
        if existing:
            return self._replay(existing, payload)

        try:
            payment = await self._uow.payments.create(
                amount=payload.amount,
                currency=payload.currency.value,
                description=payload.description,
                metadata=payload.metadata,
                idempotency_key=idempotency_key,
                webhook_url=str(payload.webhook_url),
            )

            await self._uow.outbox.create(
                event_type=EVENT_PAYMENT_CREATED,
                payload={
                    'payment_id': str(payment.id),
                    'amount': str(payment.amount),
                    'currency': payment.currency,
                    'description': payment.description,
                    'metadata': payment.metadata_,
                    'webhook_url': payment.webhook_url,
                    'idempotency_key': idempotency_key,
                },
                payment_id=payment.id,
            )
            await self._uow.commit()
        except IntegrityError:
            await self._uow.rollback()
            existing = await self._uow.payments.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            logger.info('Платёж %s создан параллельным запросом, возвращаем существующий', existing.id)
            return self._replay(existing, payload)

        return self._to_payment_response(payment)

    async def get_payment(self, payment_id: UUID) -> PaymentDetailResponse:
        """Получить детальную информацию о платеже."""
        payment = await self._uow.payments.get_by_id(payment_id)
        if not payment:
            raise PaymentNotFoundError(f'Платёж {payment_id} не найден')

        return self._to_payment_detail_response(payment)

    def _replay(self, existing: 'Payment', payload: PaymentCreateRequest) -> PaymentResponse:
        """Ответ на повторный запрос с уже известным Idempotency-Key."""
        if not self._same_request(existing, payload):
            raise IdempotencyConflictError(
                f'Idempotency-Key уже использован для платежа {existing.id} с другим телом запроса',
            )
        return self._to_payment_response(existing)

    @staticmethod
    def _same_request(payment: 'Payment', payload: PaymentCreateRequest) -> bool:
        """Сравнить сохранённый платёж с полями повторного запроса."""
        return (
            payment.amount == payload.amount
            and payment.currency == payload.currency.value
            and (payment.description or None) == (payload.description or None)
            and payment.metadata_ == payload.metadata
            and payment.webhook_url == str(payload.webhook_url)
        )

    def _to_payment_response(self, payment: 'Payment') -> PaymentResponse:
        return PaymentResponse(
            payment_id=payment.id,
            status=payment.status.value,
            created_at=payment.created_at,
        )

    def _to_payment_detail_response(self, payment: 'Payment') -> PaymentDetailResponse:
        return PaymentDetailResponse(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata=payment.metadata_,
            status=payment.status.value,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
            webhook_delivered_at=payment.webhook_delivered_at,
            failure_reason=payment.failure_reason,
        )
