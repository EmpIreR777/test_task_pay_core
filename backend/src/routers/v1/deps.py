from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import get_db
from src.repositories.unit_of_work import UnitOfWork


async def get_uow(session: AsyncSession = Depends(get_db)) -> AsyncIterator[UnitOfWork]:
    """Единица работы на HTTP-запрос: один UoW — одна сессия — одна граница транзакции."""
    async with UnitOfWork(session) as uow:
        yield uow
