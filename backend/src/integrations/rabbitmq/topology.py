import logging

from src.integrations.rabbitmq.broker import (
    EXCHANGE_DLX_OBJ,
    EXCHANGE_PAYMENTS_OBJ,
    QUEUE_PAYMENTS_DLQ,
    QUEUE_PAYMENTS_NEW,
    broker,
)

logger = logging.getLogger(__name__)


async def declare_topology() -> None:
    """Объявить обменники, очереди и их биндинги.

    Идемпотентна: повторный вызов просто переподтверждает существующие объекты.
    """
    await broker.connect()

    payments_exchange = await broker.declare_exchange(EXCHANGE_PAYMENTS_OBJ)
    dlx_exchange = await broker.declare_exchange(EXCHANGE_DLX_OBJ)

    # Биндинги обязательны: exchange topic/direct без binding отбрасывает сообщения.
    payments_queue = await broker.declare_queue(QUEUE_PAYMENTS_NEW)
    await payments_queue.bind(payments_exchange, routing_key=QUEUE_PAYMENTS_NEW.routing_key)

    dlq_queue = await broker.declare_queue(QUEUE_PAYMENTS_DLQ)
    await dlq_queue.bind(dlx_exchange, routing_key=QUEUE_PAYMENTS_DLQ.routing_key)

    logger.info('Топология RabbitMQ объявлена')
