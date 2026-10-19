from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from src.core.config import settings

broker = RabbitBroker(settings.RABBITMQ_URL)

EXCHANGE_PAYMENTS = 'payments'
EXCHANGE_DLX = f'{EXCHANGE_PAYMENTS}.dlx'

QUEUE_PAYMENTS_NEW_NAME = 'payments.new'
QUEUE_PAYMENTS_DLQ_NAME = 'payments.dlq'

ROUTING_KEY_PAYMENT_CREATED = 'payment.created'
ROUTING_KEY_PAYMENTS_DLQ = QUEUE_PAYMENTS_DLQ_NAME

# --- Обменники ---
EXCHANGE_PAYMENTS_OBJ = RabbitExchange(EXCHANGE_PAYMENTS, type=ExchangeType.TOPIC, durable=True)
EXCHANGE_DLX_OBJ = RabbitExchange(EXCHANGE_DLX, type=ExchangeType.DIRECT, durable=True)

# --- Очереди ---
QUEUE_PAYMENTS_NEW = RabbitQueue(
    QUEUE_PAYMENTS_NEW_NAME,
    durable=True,
    routing_key=ROUTING_KEY_PAYMENT_CREATED,
    arguments={
        'x-dead-letter-exchange': EXCHANGE_DLX,
        'x-dead-letter-routing-key': ROUTING_KEY_PAYMENTS_DLQ,
    },
)
QUEUE_PAYMENTS_DLQ = RabbitQueue(
    QUEUE_PAYMENTS_DLQ_NAME,
    durable=True,
    routing_key=ROUTING_KEY_PAYMENTS_DLQ,
)
