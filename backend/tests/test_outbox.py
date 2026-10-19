from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from src.models.payment import Outbox
from src.repositories.unit_of_work import UnitOfWork
from src.services.outbox_service import OutboxService


@pytest_asyncio.fixture(scope='function')
async def outbox_event(test_session_factory):
    """Создать событие в outbox."""
    async with test_session_factory() as session:
        uow = UnitOfWork(session)
        event = await uow.outbox.create(
            event_type='payment_created',
            payload={'payment_id': 'test-payment-id', 'amount': '10.00', 'currency': 'RUB'},
        )
        await uow.commit()
        return event.id


class TestOutboxService:
    """Тесты OutboxService."""

    async def test_event_is_published_and_marked_processed(self, test_session_factory, outbox_event) -> None:
        """Успешная публикация помечает событие обработанным."""
        publish = AsyncMock()

        async with test_session_factory() as session:
            uow = UnitOfWork(session)
            service = OutboxService(uow, publish, max_retries=3)
            await service.process_unpublished()

        publish.assert_awaited_once()
        assert publish.await_args.args[0]['payment_id'] == 'test-payment-id'

        async with test_session_factory() as session:
            event = await session.get(Outbox, outbox_event)
            assert event.processed_at is not None
            assert event.failed_at is None
            assert event.retry_count == 0

    async def test_publish_error_increments_retry_count(self, test_session_factory, outbox_event) -> None:
        """Ошибка публикации увеличивает счётчик ретраев и не помечает событие обработанным."""
        publish = AsyncMock(side_effect=RuntimeError('rabbit unavailable'))

        async with test_session_factory() as session:
            uow = UnitOfWork(session)
            service = OutboxService(uow, publish, max_retries=3)
            await service.process_unpublished()

        async with test_session_factory() as session:
            event = await session.get(Outbox, outbox_event)
            assert event.processed_at is None
            assert event.failed_at is None
            assert event.retry_count == 1
            assert event.last_error == 'rabbit unavailable'

    async def test_event_is_not_retried_after_max_retries(self, test_session_factory, outbox_event) -> None:
        """Событие, исчерпавшее лимит ретраев, получает терминальный статус и больше не вычитывается."""
        publish = AsyncMock(side_effect=RuntimeError('rabbit unavailable'))

        for _ in range(3):
            async with test_session_factory() as session:
                uow = UnitOfWork(session)
                service = OutboxService(uow, publish, max_retries=3)
                await service.process_unpublished()

        async with test_session_factory() as session:
            event = await session.get(Outbox, outbox_event)
            assert event.retry_count == 3
            assert event.processed_at is None
            assert event.failed_at is not None

            # Терминальное событие больше не попадает в выборку на публикацию
            uow = UnitOfWork(session)
            assert await uow.outbox.get_unprocessed() == []

    @pytest.mark.usefixtures('outbox_event')
    async def test_locked_event_is_skipped_by_second_processor(self, test_session_factory) -> None:
        """FOR UPDATE SKIP LOCKED: второй инстанс outbox-processor'а не берёт занятое событие."""
        async with test_session_factory() as first_session:
            first_uow = UnitOfWork(first_session)
            first_batch = await first_uow.outbox.get_unprocessed()
            assert len(first_batch) == 1

            # Вторая сессия работает с той же строкой — блокировка должна её пропустить.
            async with test_session_factory() as second_session:
                second_uow = UnitOfWork(second_session)
                second_batch = await second_uow.outbox.get_unprocessed()
                assert second_batch == []
