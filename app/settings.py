from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IT运维助手 Demo"
    app_env: str = "development"
    storage_backend: str = "mysql_mongo"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "ticket_service"
    mysql_user: str = "ticket_service"
    mysql_password: str = ""
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_database: str = "ticket_service"
    mongo_collection: str = "conversation_logs"
    sse_retry_ms: int = 3000
    model_name: str = ""
    model_temperature: float = 0.0
    model_max_tokens: int = 1024

    # Always resolve .env from the project root, even when an IDE runs app/cli.py directly.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
