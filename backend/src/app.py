import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.core.config import settings
from src.core.db import engine
from src.core.exception_handlers import register_exception_handlers
from src.core.logging import setup_logging
from src.routers import router as api_router

setup_logging()

logger = logging.getLogger(__name__)


async def _check_database() -> None:
    """Fail-fast проверка БД на старте: без неё приложение не имеет смысла."""
    async with engine.connect() as connection:
        await connection.execute(text('SELECT 1'))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    await _check_database()
    logger.info('Приложение запущено, соединение с базой данных в порядке')
    yield
    if not settings.TEST_MODE:
        await engine.dispose()
    logger.info('Приложение остановлено')


app = FastAPI(
    version=settings.API_VERSION,
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

register_exception_handlers(app)

app.include_router(api_router)
