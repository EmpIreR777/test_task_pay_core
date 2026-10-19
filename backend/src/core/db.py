from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

engine = create_async_engine(
    settings.SQLALCHEMY_DB_URL,
    pool_pre_ping=True,
    echo=False,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """DI-провайдер сессии БД: одна сессия на HTTP-запрос."""
    async with async_session_factory() as session:
        yield session
