"""Redis Streams 任务队列适配器。"""

from __future__ import annotations

import json
import os
from typing import Any

try:
    from redis import Redis
    from redis.exceptions import ResponseError
except ModuleNotFoundError:  # pragma: no cover - dependencies are installed in deployment images
    Redis = None  # type: ignore[assignment]

    class ResponseError(Exception):
        pass


class TaskQueue:
    """使用 Redis Streams 投递和消费后台工单任务。"""

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        stream_name: str | None = None,
        group_name: str | None = None,
    ):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.redis = Redis.from_url(self._redis_url, decode_responses=True) if Redis is not None else None
        self.stream_name = stream_name or os.getenv("REDIS_STREAM", "ticket_tasks")
        self.group_name = group_name or os.getenv("REDIS_CONSUMER_GROUP", "ticket_workers")

    def _ensure_group(self) -> None:
        if self.redis is None:
            raise RuntimeError("Redis dependency is not installed")
        try:
            self.redis.xgroup_create(self.stream_name, self.group_name, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def enqueue(self, task_id: str, payload: dict[str, Any]) -> str:
        """将任务写入 Stream，返回 Redis 消息 ID。"""
        self._ensure_group()
        assert self.redis is not None
        return self.redis.xadd(
            self.stream_name,
            {"task_id": task_id, "payload": json.dumps(payload, ensure_ascii=False)},
        )

    def consume(self, consumer_name: str, *, count: int = 1, block_ms: int = 5000) -> list[tuple[str, dict[str, str]]]:
        """阻塞读取一批新任务。"""
        self._ensure_group()
        assert self.redis is not None
        rows = self.redis.xreadgroup(
            self.group_name,
            consumer_name,
            {self.stream_name: ">"},
            count=count,
            block=block_ms,
        )
        return rows[0][1] if rows else []

    def acknowledge(self, message_id: str) -> int:
        """确认任务已处理。"""
        self._ensure_group()
        assert self.redis is not None
        return self.redis.xack(self.stream_name, self.group_name, message_id)
