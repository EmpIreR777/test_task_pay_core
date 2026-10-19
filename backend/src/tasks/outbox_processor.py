import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from faststream import FastStream

from src.core.config import settings
from src.core.db import async_session_factory
from src.core.logging import setup_logging
from src.integrations.rabbitmq.broker import broker
from src.integrations.rabbitmq.publisher import publish_payment_created
from src.integrations.rabbitmq.topology import declare_topology
from src.repositories.unit_of_work import UnitOfWork
from src.services.outbox_service import OutboxService

setup_logging()

logger = logging.getLogger(__name__)

_poll_task: asyncio.Task[None] | None = None


async def process_outbox() -> None:
    """Обработать одну партию неопубликованных событий из outbox."""
    async with async_session_factory() as session:
        uow = UnitOfWork(session)
        service = OutboxService(uow, publish_payment_created, max_retries=settings.OUTBOX_MAX_RETRIES)
        await service.process_unpublished(limit=settings.OUTBOX_BATCH_SIZE)


async def poll_outbox() -> None:
    """Публиковать накопленные события с интервалом OUTBOX_POLL_INTERVAL."""
    while True:
        try:
            await process_outbox()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception('Ошибка в цикле outbox processor: %s', exc)

        await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL)


@asynccontextmanager
async def lifespan() -> AsyncGenerator[None]:
    """Объявить топологию до старта опроса."""
    await declare_topology()
    try:
        yield
    finally:
        await _stop_polling()


app = FastStream(broker, lifespan=lifespan)


@app.after_startup
async def start_polling() -> None:
    """Стартовать опрос только после того, как брокер поднят."""
    global _poll_task
    _poll_task = asyncio.create_task(poll_outbox())
    logger.info(
        'Outbox processor стартовал (интервал: %dс, батч: %d)',
        settings.OUTBOX_POLL_INTERVAL,
        settings.OUTBOX_BATCH_SIZE,
    )


async def _stop_polling() -> None:
    global _poll_task
    if _poll_task is not None:
        _poll_task.cancel()
        with suppress(asyncio.CancelledError):
            await _poll_task
        _poll_task = None
        logger.info('Outbox processor остановлен')
