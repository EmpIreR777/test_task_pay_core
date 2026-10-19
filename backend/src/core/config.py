from pathlib import Path

from pydantic import computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # <project>/backend/src
ENV_FILE_PATH = BASE_DIR.parent.parent / '.env'  # <project>/.env


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из переменных окружения и .env файла."""

    model_config = SettingsConfigDict(env_file=str(ENV_FILE_PATH), extra='ignore')

    # --- API ---
    API_PREFIX: str = '/api/v1'
    API_VERSION: str = '0.1.0'
    API_TITLE: str = 'Payment Processing API'
    API_DESCRIPTION: str = 'Асинхронный сервис процессинга платежей'

    # Разрешённые origin'ы для CORS
    CORS_ORIGINS: list[str] = [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ]

    # --- Аутентификация ---
    # Статический API ключ для заголовка X-API-Key (обязательно, >= 32 символа)
    API_KEY: str

    # --- Postgres ---
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    # Тесты работают в отдельной БД, чтобы не оставлять мусор в рабочей.
    TEST_POSTGRES_DB: str = 'payment_processing_test'

    # --- RabbitMQ ---
    RABBITMQ_URL: str = 'amqp://guest:guest@rabbitmq:5672//'

    # --- Webhook ---
    WEBHOOK_TIMEOUT: int = 10
    WEBHOOK_MAX_RETRIES: int = 3

    # --- Outbox Processor ---
    OUTBOX_POLL_INTERVAL: int = 5
    OUTBOX_BATCH_SIZE: int = 100
    OUTBOX_MAX_RETRIES: int = 3

    # --- Consumer ---
    CONSUMER_MAX_RETRIES: int = 3
    CONSUMER_RETRY_BASE_DELAY: float = 1.0

    # --- Наблюдаемость ---
    LOG_LEVEL: str = 'INFO'

    # --- Test mode ---
    TEST_MODE: bool = False

    def build_database_url(self, scheme: str, db_name: str | None = None) -> str:
        return str(
            MultiHostUrl.build(
                scheme=scheme,
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=db_name or self.POSTGRES_DB,
            ),
        )

    @property
    def target_db_name(self) -> str:
        """БД, с которой работает приложение: тестовая в TEST_MODE, иначе боевая."""
        return self.TEST_POSTGRES_DB if self.TEST_MODE else self.POSTGRES_DB

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DB_URL(self) -> str:  # noqa: N802
        return self.build_database_url('postgresql+asyncpg', self.target_db_name)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_SYNC_DB_URL(self) -> str:  # noqa: N802
        return self.build_database_url('postgresql+psycopg2', self.target_db_name)


settings = Settings()
