from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest_asyncio

from src.core import db
from src.integrations.rabbitmq import consumer  # noqa: F401 - регистрирует subscriber
from src.integrations.rabbitmq.consumer import process_payment
from src.models.payment import Payment, PaymentStatus
from src.repositories.payment_repo import PaymentRepository


@pytest_asyncio.fixture(scope='function')
async def test_payment(test_session_factory):
    """Создать тестовый платёж в БД."""
    async with test_session_factory() as session:
        repo = PaymentRepository(session)
        payment = await repo.create(
            amount=Decimal('100.50'),
            currency='RUB',
            description='Test payment',
            metadata={'order_id': '123'},
            idempotency_key=f'test-key-{uuid4()}',
            webhook_url='https://example.com/webhook',
        )
        await session.commit()
        await session.refresh(payment)
        return payment


@pytest_asyncio.fixture(scope='function')
def mock_rabbit_message():
    """Создать мок RabbitMessage."""
    msg = MagicMock()
    msg.headers = {}
    msg.nack = AsyncMock()
    return msg


@pytest_asyncio.fixture(scope='function', autouse=True)
async def override_db_session_factory(test_session_factory, test_engine):
    """Переопределить фабрику сессий в src.core.db для consumer'а."""
    original_session_factory = db.async_session_factory
    original_engine = db.engine
    db.async_session_factory = test_session_factory
    db.engine = test_engine
    yield
    db.async_session_factory = original_session_factory
    db.engine = original_engine


class TestConsumer:
    """Тесты consumer'a."""

    async def test_process_payment_success(
        self,
        test_payment: Payment,
        test_session_factory,
        mock_rabbit_message,
    ) -> None:
        """Успешная обработка платежа."""
        message = {
            'payment_id': str(test_payment.id),
            'amount': str(test_payment.amount),
            'currency': test_payment.currency,
            'webhook_url': test_payment.webhook_url,
        }

        with (
            patch('src.services.payment_processing.send_webhook', new_callable=AsyncMock),
            patch('src.services.payment_processing.asyncio.sleep', new_callable=AsyncMock),
            patch('src.services.payment_processing.random.random', return_value=0.0),
        ):
            await process_payment(message, mock_rabbit_message)

        mock_rabbit_message.nack.assert_not_awaited()

        async with test_session_factory() as session:
            repo = PaymentRepository(session)
            updated = await repo.get_by_id(test_payment.id)
            assert updated.status == PaymentStatus.SUCCEEDED
            assert updated.processed_at is not None
            # Уведомление доставлено — факт зафиксирован в БД
            assert updated.webhook_delivered_at is not None

    async def test_process_payment_failed(
        self,
        test_payment: Payment,
        test_session_factory,
        mock_rabbit_message,
    ) -> None:
        """Обработка платежа с ошибкой (10% случаев)."""
        message = {
            'payment_id': str(test_payment.id),
            'amount': str(test_payment.amount),
            'currency': test_payment.currency,
            'webhook_url': test_payment.webhook_url,
        }

        with (
            patch('src.services.payment_processing.send_webhook', new_callable=AsyncMock),
            patch('src.services.payment_processing.asyncio.sleep', new_callable=AsyncMock),
            patch('src.services.payment_processing.random.random', return_value=0.95),
        ):
            await process_payment(message, mock_rabbit_message)

        async with test_session_factory() as session:
            repo = PaymentRepository(session)
            updated = await repo.get_by_id(test_payment.id)
            assert updated.status == PaymentStatus.FAILED
            assert updated.processed_at is not None

    async def test_process_payment_idempotency(
        self,
        test_payment: Payment,
        test_session_factory,
        mock_rabbit_message,
    ) -> None:
        """Идемпотентность: повторная обработка не меняет статус."""
        async with test_session_factory() as session:
            repo = PaymentRepository(session)
            await repo.transition_status(test_payment.id, PaymentStatus.SUCCEEDED)
            await session.commit()

        message = {
            'payment_id': str(test_payment.id),
            'amount': str(test_payment.amount),
            'currency': test_payment.currency,
            'webhook_url': test_payment.webhook_url,
        }

        with (
            patch('src.services.payment_processing.asyncio.sleep', new_callable=AsyncMock),
            patch('src.services.payment_processing.random.random', return_value=0.0),
        ):
            await process_payment(message, mock_rabbit_message)

        async with test_session_factory() as session:
            repo = PaymentRepository(session)
            updated = await repo.get_by_id(test_payment.id)
            assert updated.status == PaymentStatus.SUCCEEDED

    async def test_process_payment_webhook_failure_does_not_reexecute(
        self,
        test_payment: Payment,
        test_session_factory,
        mock_rabbit_message,
    ) -> None:
        """Недоставленный вебхук не отправляет сообщение в DLQ и не меняет статус."""
        message = {
            'payment_id': str(test_payment.id),
            'amount': str(test_payment.amount),
            'currency': test_payment.currency,
            'webhook_url': test_payment.webhook_url,
        }

        with (
            patch(
                'src.services.payment_processing.send_webhook',
                new_callable=AsyncMock,
                side_effect=RuntimeError('502'),
            ),
            patch('src.services.payment_processing.asyncio.sleep', new_callable=AsyncMock),
            patch('src.services.payment_processing.random.random', return_value=0.0),
        ):
            await process_payment(message, mock_rabbit_message)

        mock_rabbit_message.nack.assert_not_awaited()

        async with test_session_factory() as session:
            repo = PaymentRepository(session)
            updated = await repo.get_by_id(test_payment.id)
            assert updated.status == PaymentStatus.SUCCEEDED

    async def test_process_payment_retries_and_goes_to_dlq(
        self,
        test_payment: Payment,
        test_session_factory,
        mock_rabbit_message,
    ) -> None:
        """Три неудачные попытки — сообщение уходит в DLQ, платёж становится failed."""
        message = {
            'payment_id': str(test_payment.id),
            'amount': str(test_payment.amount),
            'currency': test_payment.currency,
            'webhook_url': test_payment.webhook_url,
        }

        with (
            patch('src.services.payment_processing.asyncio.sleep', new_callable=AsyncMock),
            patch(
                'src.integrations.rabbitmq.consumer.PaymentProcessingService.process',
                new_callable=AsyncMock,
                side_effect=RuntimeError('gateway timeout'),
            ),
        ):
            await process_payment(message, mock_rabbit_message)

        mock_rabbit_message.nack.assert_awaited_once_with(requeue=False)

        async with test_session_factory() as session:
            repo = PaymentRepository(session)
            updated = await repo.get_by_id(test_payment.id)
            assert updated.status == PaymentStatus.FAILED
            assert updated.failure_reason is not None

    async def test_process_payment_unknown_payment_goes_to_dlq(
        self,
        mock_rabbit_message,
    ) -> None:
        """Сообщение о несуществующем платеже уходит в DLQ без повторных попыток."""
        message = {
            'payment_id': str(uuid4()),
            'amount': '10.00',
            'currency': 'RUB',
            'webhook_url': 'https://example.com/webhook',
        }

        with patch('src.integrations.rabbitmq.consumer.asyncio.sleep', new_callable=AsyncMock):
            await process_payment(message, mock_rabbit_message)

        mock_rabbit_message.nack.assert_awaited_once_with(requeue=False)
