from src.integrations.rabbitmq.broker import (
    EXCHANGE_PAYMENTS_OBJ,
    ROUTING_KEY_PAYMENT_CREATED,
    broker,
)


async def publish_payment_created(payload: dict[str, object]) -> None:
    """Опубликовать событие создания платежа в очередь payments.new.

    persist=True — сообщение переживает перезапуск брокера.
    mandatory (по умолчанию True) — если routing key не найдёт очередь,
    publish бросит исключение и событие останется в outbox на повтор.
    """
    await broker.publish(
        payload,
        exchange=EXCHANGE_PAYMENTS_OBJ,
        routing_key=ROUTING_KEY_PAYMENT_CREATED,
        persist=True,
    )
