import logging
import sys
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


def run_migrations_with_retry(max_attempts: int = 3, delay: int = 4) -> None:
    """Запускает миграции с повторными попытками при ошибках подключения."""
    attempt = 0
    while attempt < max_attempts:
        try:
            run_migrations()
            return
        except SQLAlchemyError as e:
            attempt += 1
            if attempt == max_attempts:
                logger.error('❌ Потерпел неудачу после %d попыток: %s', max_attempts, e)
                raise
            logger.warning('⚠️  Ошибка соединения (попытка %d/%d): %s', attempt, max_attempts, e)
            time.sleep(delay)


def run_migrations() -> None:
    """Запуск Alembic миграций."""
    sync_url = settings.SQLALCHEMY_SYNC_DB_URL
    engine = create_engine(sync_url)

    try:
        # Проверяем подключение
        check_connection(engine)

        # Запускаем миграции
        migrations_path = BASE_DIR.parent / 'alembic'
        alembic_cfg = Config()
        alembic_cfg.set_main_option('script_location', str(migrations_path))
        alembic_cfg.set_main_option('sqlalchemy.url', sync_url)

        logger.info('🔄 Применяем миграции alembic...')
        command.upgrade(alembic_cfg, 'head')

        logger.info('✅ Миграция завершена успешно')

    except Exception as e:
        logger.error('❌ Ошибка во время миграции: %s', e)
        raise
    finally:
        engine.dispose()


def check_connection(engine: Engine) -> bool:
    """Проверяет соединение с базой данных."""
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
            logger.info('✅ Проверка подключения к базе данных: успешно')
            return True
    except Exception as e:
        logger.error('❌ Не удалось проверить подключение к базе данных: %s', e)
        return False


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(name)s - %(message)s')
    logger.info('🚀 Начинаю процесс миграции БД...')
    try:
        run_migrations_with_retry()
        logger.info('✅ Все миграции успешно применены!')
        sys.exit(0)
    except Exception as e:
        logger.error('❌ Критическая ошибка при выполнении миграций: %s', e)
        sys.exit(1)
