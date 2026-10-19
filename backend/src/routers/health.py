import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.db import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=['health'])


@router.get('/health')
async def health() -> dict[str, str]:
    """Liveness: процесс жив (без обращения к зависимостям)."""
    return {'status': 'ok'}


@router.get('/health/full')
async def health_full() -> JSONResponse:
    """Readiness: проверяем соединение с БД."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text('SELECT 1'))
    except Exception:
        logger.exception('Readiness-проверка базы данных не прошла')
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={'status': 'degraded', 'database': 'unavailable'},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={'status': 'ok', 'database': 'ok'})
