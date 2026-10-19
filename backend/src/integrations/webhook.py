import json
import logging
from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Общий HTTP-клиент с keep-alive: на каждый вебхук не поднимаем соединение заново."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
    return _client


async def close_client() -> None:
    """Закрыть общий клиент (вызывается при остановке процесса)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def build_payload(
    *,
    payment_id: str,
    status: str,
    amount: Decimal,
    currency: str,
    event: str,
    processed_at: datetime | None = None,
) -> dict[str, Any]:
    """Тело уведомления."""
    payload: dict[str, Any] = {
        'event': event,
        'payment_id': payment_id,
        'status': status,
        'amount': str(amount),
        'currency': currency,
    }
    if processed_at is not None:
        payload['processed_at'] = processed_at.isoformat()
    return payload


async def send_webhook(
    url: str,
    payment_id: str,
    status: str,
    amount: Decimal,
    currency: str,
    event: str = 'payment.processed',
    processed_at: datetime | None = None,
    timeout: int = 10,
) -> None:
    """Отправить webhook уведомление на указанный URL.

    Тело уведомления фиксировано и сериализуется один раз, поэтому клиент
    получает ровно то, что ожидает, и может спокойно его разобрать.
    """
    payload = build_payload(
        payment_id=payment_id,
        status=status,
        amount=amount,
        currency=currency,
        event=event,
        processed_at=processed_at,
    )
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

    headers = {'Content-Type': 'application/json'}

    response = await get_client().post(url, content=body, headers=headers, timeout=timeout)
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        logger.warning('Webhook вернул %s для платежа %s', response.status_code, payment_id)
    response.raise_for_status()
