from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://learnmentor:learnmentor@localhost:5432/learnmentor"
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Security
    llm_encryption_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()
