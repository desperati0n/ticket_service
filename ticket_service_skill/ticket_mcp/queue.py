"""Redis Streams transport between the MCP frontend and ticket backend."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import threading
import time
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError

from .config import Settings


TERMINAL_STATES = {"success", "failed"}


class RedisTicketQueue:
    """Durable command queue plus short-lived task result storage."""

    def __init__(self, settings: Settings, *, redis_client: Any | None = None):
        self.redis = redis_client or Redis.from_url(settings.redis_url, decode_responses=True)
        self.stream_name = settings.redis_stream
        self.group_name = settings.redis_consumer_group
        self.pending_idle_ms = settings.redis_pending_idle_ms
        self.heartbeat_interval_seconds = settings.redis_heartbeat_interval_seconds
        self.result_ttl_seconds = settings.redis_result_ttl_seconds
        if self.pending_idle_ms <= self.heartbeat_interval_seconds * 1000:
            raise ValueError("REDIS_PENDING_IDLE_MS must exceed the heartbeat interval")

    def _task_key(self, task_id: str) -> str:
        return f"ticket_mcp_task:{task_id}"

    def _ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(self.stream_name, self.group_name, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def _write_state(self, task_id: str, state: dict[str, Any]) -> None:
        self.redis.setex(
            self._task_key(task_id),
            self.result_ttl_seconds,
            json.dumps({"task_id": task_id, **state}, ensure_ascii=False),
        )

    def enqueue(self, task_id: str, operation: str, payload: dict[str, Any]) -> str:
        """Persist queued state, then append a command to the stream."""
        self._ensure_group()
        self._write_state(task_id, {"status": "queued"})
        try:
            return self.redis.xadd(
                self.stream_name,
                {
                    "task_id": task_id,
                    "operation": operation,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        except Exception:
            self.redis.delete(self._task_key(task_id))
            raise

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        raw = self.redis.get(self._task_key(task_id))
        return json.loads(raw) if raw else None

    def mark_processing(self, task_id: str) -> None:
        self._write_state(task_id, {"status": "processing"})

    def complete(self, task_id: str, result: dict[str, Any]) -> None:
        self._write_state(task_id, {"status": "success", "result": result})

    def fail(self, task_id: str, error: str) -> None:
        self._write_state(task_id, {"status": "failed", "error": error})

    def wait_for_terminal(
        self,
        task_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            task = self.get_task(task_id)
            if task is not None and task.get("status") in TERMINAL_STATES:
                return task
            if time.monotonic() >= deadline:
                return task
            time.sleep(poll_interval_seconds)

    def consume(
        self, consumer_name: str, *, count: int = 1, block_ms: int = 5000
    ) -> list[tuple[str, dict[str, str]]]:
        """Reclaim stale work first, then block for new commands."""
        self._ensure_group()
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
        acknowledged = self.redis.xack(self.stream_name, self.group_name, message_id)
        if acknowledged:
            try:
                self.redis.xdel(self.stream_name, message_id)
            except Exception:
                pass
        return acknowledged

    def touch(self, message_id: str, consumer_name: str) -> None:
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
        """Refresh pending ownership while the backend executes a command."""
        stopped = threading.Event()

        def heartbeat() -> None:
            while not stopped.wait(self.heartbeat_interval_seconds):
                try:
                    self.touch(message_id, consumer_name)
                except Exception:
                    continue

        thread = threading.Thread(
            target=heartbeat,
            name=f"redis-heartbeat-{message_id}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=self.heartbeat_interval_seconds)
