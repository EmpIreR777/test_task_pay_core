import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.core.exceptions import AppError

logger = logging.getLogger(__name__)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Перевод доменных исключений в HTTP-коды — единая точка вместо try/except в роутерах."""
    logger.warning('Ошибка домена %s на %s %s: %s', exc.status_code, request.method, request.url.path, exc.message)
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.message})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """500 на любую неожиданную ошибку — наружу не отдаём детали, только в лог/Sentry."""
    logger.exception('Необработанная ошибка на %s %s', request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={'detail': 'Internal Server Error'},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Подключить глобальные обработчики ошибок к приложению."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
