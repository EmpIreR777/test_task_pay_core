from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from src.core.config import settings
from src.core.constants import MAX_IDEMPOTENCY_KEY_LENGTH
from src.core.security import verify_api_key
from src.repositories.unit_of_work import UnitOfWork
from src.routers.v1.deps import get_uow
from src.schemas.payment import PaymentCreateRequest, PaymentDetailResponse, PaymentResponse
from src.services.payment_service import PaymentService

router = APIRouter(prefix=f'{settings.API_PREFIX}/payments', tags=['payments'])


# Основной путь — без завершающего слэша (как в ТЗ: POST /api/v1/payments).
# Вариант со слэшем тоже принимается, но в OpenAPI не дублируется.
@router.post(
    '',
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary='Создать платёж',
)
@router.post(
    '/',
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary='Создать платёж',
    include_in_schema=False,
)
async def create_payment(
    payload: PaymentCreateRequest,
    idempotency_key: str = Header(
        ...,
        alias='Idempotency-Key',
        min_length=1,
        max_length=MAX_IDEMPOTENCY_KEY_LENGTH,
        pattern=r'^\S+$',
    ),
    api_key: str = Depends(verify_api_key),
    uow: UnitOfWork = Depends(get_uow),
) -> PaymentResponse:
    """Создать новый платёж."""
    service = PaymentService(uow)
    return await service.create_payment(payload=payload, idempotency_key=idempotency_key)


@router.get(
    '/{payment_id}',
    response_model=PaymentDetailResponse,
    summary='Получить информацию о платеже',
)
async def get_payment(
    payment_id: UUID,
    api_key: str = Depends(verify_api_key),
    uow: UnitOfWork = Depends(get_uow),
) -> PaymentDetailResponse:
    """Получить детальную информацию о платеже по ID."""
    service = PaymentService(uow)
    return await service.get_payment(payment_id=payment_id)
