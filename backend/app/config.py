from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://socratiq:socratiq@localhost:5432/socratiq"
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Security
    llm_encryption_key: str = ""

    # Bilibili (optional — for authenticated subtitle access)
    bilibili_sessdata: str = ""
    bilibili_bili_jct: str = ""
    bilibili_buvid3: str = ""

    # File uploads
    upload_dir: str = "uploads"

    # Whisper ASR (fallback when no subtitles available)
    whisper_mode: str = "local"      # "api" = OpenAI Whisper API, "local" = local whisper model
    whisper_model: str = "base"      # local model size: tiny/base/small/medium/large

    # Auth
    jwt_secret_key: str = "change-me-in-production"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    google_client_id: str = ""

    # Observability
    sentry_dsn: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()
