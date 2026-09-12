from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # LLM — Groq free tier only. Which Groq model handles which pipeline node
    # is configured in app/core/model_router.py, not here.
    GROQ_API_KEY: str
    LLM_TEMPERATURE: float = 0.3
    LLM_TIMEOUT: int = 30

    # Port 5433, not 5432 — see docker-compose.yml's postgres service comment:
    # host 5432 may already be taken by a native PostgreSQL install.
    DATABASE_URL: str = "postgresql+asyncpg://code_motion:code_motion@localhost:5433/code_motion"
    REDIS_URL: str = "redis://localhost:6379/0"
    MEDIA_DIR: str = "media"
    APP_ENV: str = "development"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Alembic and the Celery worker use a sync driver (psycopg), not asyncpg."""
        return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg")


settings = Settings()
