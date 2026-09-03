"""本模块从项目根目录的 .env 文件读取环境配置。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """配置模型将环境变量映射为带类型的运行参数。"""
    app_name: str = "IT运维助手 Demo"
    app_env: str = "development"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "ticket_service"
    mysql_user: str = "ticket_service"
    mysql_password: str = ""
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_database: str = "ticket_service"
    mongo_collection: str = "conversation_logs"
    adminer_port: int = 8080
    mongo_express_port: int = 8081
    mongo_express_auth_enabled: bool = True
    mongo_express_username: str = "admin"
    mongo_express_password: str = "change-me"
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
    """返回当前进程复用的配置对象。"""
    return Settings()
