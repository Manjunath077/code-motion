from pydantic import model_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # LLM — OpenRouter, free models only (see NEW_PLAN.md Section 4). Which
    # model handles which pipeline stage is decided in app/core/model_router.py
    # by referring to these settings — model IDs never appear in code.
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    MODEL_ULTRA: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    MODEL_VL: str = "nvidia/nemotron-3.5-super-vl:free"
    MODEL_LIGHTNING: str = "nvidia/nemotron-3.5-lightning:free"
    # :free models allow 20 req/min account-wide; stay a little under it.
    LLM_RPM: int = 18
    # Stop calling the LLM when fewer than this many free requests remain today.
    LLM_DAILY_RESERVE: int = 50
    LLM_MAX_TOKENS: int = 16000
    LLM_TEMPERATURE: float = 0.3
    # Ultra on a long codegen can take well over a minute.
    LLM_TIMEOUT: int = 120

    # Port 5433, not 5432 — see docker-compose.yml's postgres service comment:
    # host 5432 may already be taken by a native PostgreSQL install.
    DATABASE_URL: str = "postgresql+asyncpg://code_motion:code_motion@localhost:5433/code_motion"
    REDIS_URL: str = "redis://localhost:6379/0"
    MEDIA_DIR: str = "media"
    APP_ENV: str = "development"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _only_free_models(self) -> "Settings":
        """Fail boot (API and Celery worker alike) if any configured model ID
        is not a free one — a non-:free ID bills real credits."""
        for name in ("MODEL_ULTRA", "MODEL_VL", "MODEL_LIGHTNING"):
            value = getattr(self, name)
            if not value.endswith(":free"):
                raise ValueError(f"{name}={value!r} must end in ':free' — paid models are not allowed")
        return self

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Alembic and the Celery worker use a sync driver (psycopg), not asyncpg."""
        return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg")


settings = Settings()
