"""Environment-driven MCP, queue, and database settings."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    """All runtime settings; secrets remain outside the Skill bundle."""

    mcp_host: str
    mcp_port: int
    mcp_public_url: str
    mcp_bearer_token: str | None
    mcp_queue_timeout_seconds: float
    mcp_queue_poll_interval_seconds: float
    snowflake_worker_id: int
    redis_url: str
    redis_stream: str
    redis_consumer_group: str
    redis_pending_idle_ms: int
    redis_heartbeat_interval_seconds: float
    redis_result_ttl_seconds: int
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    mongo_uri: str
    mongo_database: str
    mongo_collection: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        token = os.getenv("MCP_BEARER_TOKEN", "").strip() or None
        return cls(
            mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
            mcp_port=int(os.getenv("MCP_PORT", "8000")),
            mcp_public_url=os.getenv("MCP_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
            mcp_bearer_token=token,
            mcp_queue_timeout_seconds=float(os.getenv("MCP_QUEUE_TIMEOUT_SECONDS", "30")),
            mcp_queue_poll_interval_seconds=float(
                os.getenv("MCP_QUEUE_POLL_INTERVAL_SECONDS", "0.1")
            ),
            snowflake_worker_id=int(os.getenv("SNOWFLAKE_WORKER_ID", "1")),
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            redis_stream=os.getenv("REDIS_STREAM", "ticket_commands"),
            redis_consumer_group=os.getenv("REDIS_CONSUMER_GROUP", "ticket_backends"),
            redis_pending_idle_ms=int(os.getenv("REDIS_PENDING_IDLE_MS", "120000")),
            redis_heartbeat_interval_seconds=float(
                os.getenv("REDIS_HEARTBEAT_INTERVAL_SECONDS", "30")
            ),
            redis_result_ttl_seconds=int(os.getenv("REDIS_RESULT_TTL_SECONDS", "86400")),
            mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_database=os.getenv("MYSQL_DATABASE", "ticket_service"),
            mysql_user=os.getenv("MYSQL_USER", "ticket_service"),
            mysql_password=os.getenv("MYSQL_PASSWORD", ""),
            mongo_uri=os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"),
            mongo_database=os.getenv("MONGO_DATABASE", "ticket_service"),
            mongo_collection=os.getenv("MONGO_COLLECTION", "conversation_logs"),
        )
