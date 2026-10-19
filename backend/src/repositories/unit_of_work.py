from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.payment_repo import OutboxRepository, PaymentRepository


class UnitOfWork:
    """Единица работы: управляет транзакцией и репозиториями."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.payments = PaymentRepository(session)
        self.outbox = OutboxRepository(session)

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        if exc_type is not None:
            await self._session.rollback()
        else:
            await self._session.commit()
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
