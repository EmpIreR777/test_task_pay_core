from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from faststream import FastStream

from src.core.logging import setup_logging
from src.integrations.rabbitmq.broker import broker
from src.integrations.rabbitmq.consumer import process_payment  # noqa: F401 - регистрирует subscriber
from src.integrations.rabbitmq.topology import declare_topology
from src.integrations.webhook import close_client

setup_logging()


@asynccontextmanager
async def lifespan() -> AsyncGenerator[None]:
    """Объявить топологию до старта подписки и закрыть HTTP-клиент на остановке."""
    await declare_topology()
    try:
        yield
    finally:
        await close_client()


app = FastStream(broker, lifespan=lifespan)
