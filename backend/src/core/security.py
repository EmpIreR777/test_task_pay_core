import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from src.core.config import settings

api_key_header = APIKeyHeader(name='X-API-Key', auto_error=False)


async def verify_api_key(
    api_key: str | None = Depends(api_key_header),
) -> str:
    """
    Проверить API ключ из заголовка X-API-Key.
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Заголовок X-API-Key не передан',
        )
    if not secrets.compare_digest(api_key.strip().encode(), settings.API_KEY.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Неверный API ключ',
        )
    return api_key
