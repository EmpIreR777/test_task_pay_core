import os

# TEST_MODE выставляется до импорта src.*: от него зависит, какую БД
# использует приложение (тестовую или рабочую) — в том числе alembic и engine.
os.environ['TEST_MODE'] = 'true'

from collections.abc import AsyncIterator
from uuid import uuid4

import psycopg2
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.app import app
from src.core.config import settings

settings.API_KEY = 'test-api-key-0123456789abcdef'  # Overwrite for tests to guarantee valid key


def pytest_configure(config):
    """Создать тестовую БД и применить миграции."""
    _create_test_database()
    alembic_cfg = Config('alembic.ini')
    command.upgrade(alembic_cfg, 'head')


def _create_test_database() -> None:
    """Создать тестовую БД, если её ещё нет (CREATE DATABASE не идёт в транзакции)."""
    connection = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname='postgres',
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (settings.TEST_POSTGRES_DB,))
            if cursor.fetchone() is None:
                cursor.execute(f'CREATE DATABASE {settings.TEST_POSTGRES_DB}')
    finally:
        connection.close()


@pytest_asyncio.fixture(scope='function')
async def test_engine():
    """Создать тестовый движок БД."""
    test_database_url = settings.SQLALCHEMY_DB_URL
    engine = create_async_engine(
        test_database_url,
        pool_pre_ping=True,
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope='function')
async def test_session_factory(test_engine):
    """Создать фабрику сессий для тестов."""
    return async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(scope='function', autouse=True)
async def clean_tables(test_session_factory):
    """Очистить таблицы до и после теста: тесты не должны зависеть от порядка запуска."""
    async with test_session_factory() as session:
        await session.execute(text('TRUNCATE payments, outbox'))
        await session.commit()

    yield

    async with test_session_factory() as session:
        await session.execute(text('TRUNCATE payments, outbox'))
        await session.commit()


@pytest_asyncio.fixture(scope='function')
async def client(test_session_factory, test_engine) -> AsyncIterator[AsyncClient]:
    """HTTP клиент для тестирования API."""
    # Переопределяем engine и session_factory в src.core.db
    import src.core.db

    original_engine = src.core.db.engine
    original_session_factory = src.core.db.async_session_factory

    src.core.db.engine = test_engine
    src.core.db.async_session_factory = test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as ac:
        yield ac

    # Восстанавливаем оригинальные значения
    src.core.db.engine = original_engine
    src.core.db.async_session_factory = original_session_factory


@pytest_asyncio.fixture(scope='function')
async def api_key() -> str:
    """Валидный API ключ для тестов."""
    return settings.API_KEY


@pytest_asyncio.fixture(scope='function')
async def idempotency_key() -> str:
    """Уникальный ключ идемпотентности для теста."""
    return f'test-key-{uuid4()}'


@pytest_asyncio.fixture(scope='function')
async def payment_data(idempotency_key: str) -> dict:
    """Данные для создания платежа."""
    return {
        'amount': '100.50',
        'currency': 'RUB',
        'description': 'Test payment',
        'metadata': {'order_id': '123'},
        'webhook_url': 'https://example.com/webhook',
        'idempotency_key': idempotency_key,
    }
