import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from src.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class OutboxService:
    """Публикация событий из outbox в брокер."""

    def __init__(
        self,
        uow: UnitOfWork,
        publish: Callable[[dict[str, Any]], Awaitable[None]],
        max_retries: int = 3,
    ) -> None:
        self._uow = uow
        self._publish = publish
        self._max_retries = max_retries

    async def process_unpublished(self, limit: int = 100) -> None:
        events = await self._uow.outbox.get_unprocessed(limit=limit)
        if not events:
            return

        logger.info('Обрабатываем %d событий из outbox', len(events))

        for event in events:
            try:
                await self._publish(event.payload)
            except Exception as exc:
                retry_count = await self._uow.outbox.mark_publish_failure(event.id, str(exc), self._max_retries)
                if retry_count >= self._max_retries:
                    logger.error(
                        'Событие %s (%s) не опубликовано после %d попыток — помечено как необработанное',
                        event.id,
                        event.event_type,
                        retry_count,
                    )
                else:
                    logger.warning(
                        'Ошибка публикации события %s (%s), попытка %d/%d: %s',
                        event.id,
                        event.event_type,
                        retry_count,
                        self._max_retries,
                        exc,
                    )
                continue

            event.processed_at = datetime.now(UTC)
            logger.info('Событие %s (%s) опубликовано', event.id, event.event_type)
        await self._uow.commit()
