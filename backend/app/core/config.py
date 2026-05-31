from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # LLM — provider-agnostic via LiteLLM
    # Model format: "gpt-4o-mini" | "anthropic/claude-3-haiku-20240307"
    #               "gemini/gemini-1.5-flash" | "groq/llama-3.1-8b-instant"
    #               "ollama/llama3" | any LiteLLM-supported model string
    LLM_API_KEY: str
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_BASE_URL: str = ""          # leave empty unless using custom/self-hosted endpoint
    LLM_TEMPERATURE: float = 0.3
    LLM_TIMEOUT: int = 30

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "code-motion"
    REDIS_URL: str = "redis://localhost:6379/0"
    MEDIA_DIR: str = "media"
    APP_ENV: str = "development"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]


settings = Settings()
