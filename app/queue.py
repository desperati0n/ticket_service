"""Redis Streams 任务队列适配器。"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
        self.pending_idle_ms = int(os.getenv("REDIS_PENDING_IDLE_MS", "120000"))
        self.heartbeat_interval_seconds = float(os.getenv("REDIS_HEARTBEAT_INTERVAL_SECONDS", "30"))
        if self.pending_idle_ms <= self.heartbeat_interval_seconds * 1000:
            raise ValueError("REDIS_PENDING_IDLE_MS must be greater than the heartbeat interval")

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
        """优先认领超时任务，否则阻塞读取一批新任务。"""
        self._ensure_group()
        assert self.redis is not None
        claimed = self.redis.xautoclaim(
            self.stream_name,
            self.group_name,
            consumer_name,
            min_idle_time=self.pending_idle_ms,
            start_id="0-0",
            count=count,
        )
        pending = claimed[1] if len(claimed) > 1 else []
        if pending:
            return pending
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

    def touch(self, message_id: str, consumer_name: str) -> None:
        """刷新处理中消息的空闲时间，防止被其他 Worker 误认领。"""
        self._ensure_group()
        assert self.redis is not None
        self.redis.xclaim(
            self.stream_name,
            self.group_name,
            consumer_name,
            min_idle_time=0,
            message_ids=[message_id],
            justid=True,
        )

    @contextmanager
    def maintain_ownership(self, message_id: str, consumer_name: str) -> Iterator[None]:
        """处理任务期间定时刷新消息所有权。"""
        stopped = threading.Event()

        def heartbeat() -> None:
            while not stopped.wait(self.heartbeat_interval_seconds):
                try:
                    self.touch(message_id, consumer_name)
                except Exception:
                    # Redis 暂时不可用时让主处理继续；最终 ACK 失败后仍可被重新认领。
                    continue

        thread = threading.Thread(target=heartbeat, name=f"redis-heartbeat-{message_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=self.heartbeat_interval_seconds)
