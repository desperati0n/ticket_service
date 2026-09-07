"""使用 Redis 保存浏览器会话与当前对话的映射。"""

from __future__ import annotations

import os

try:
    from redis import Redis
except ModuleNotFoundError:  # pragma: no cover - 部署镜像会安装 Redis
    Redis = None  # type: ignore[assignment]


SESSION_COOKIE_NAME = "ticket_session_id"


class ConversationSessionStore:
    """在 Redis 中保存每个客户端会话的当前对话。"""

    def __init__(self, redis_url: str | None = None):
        url = redis_url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.redis = Redis.from_url(url, decode_responses=True) if Redis is not None else None
        self.ttl_seconds = int(os.getenv("CONVERSATION_SESSION_TTL_SECONDS", "604800"))

    @staticmethod
    def _key(session_id: str) -> str:
        return f"ticket_session:{session_id}:conversation"

    def get(self, session_id: str) -> str | None:
        """返回当前对话并刷新会话有效期。"""
        if self.redis is None:
            raise RuntimeError("Redis dependency is not installed")
        key = self._key(session_id)
        conversation_id = self.redis.get(key)
        if conversation_id is not None:
            self.redis.expire(key, self.ttl_seconds)
        return conversation_id

    def set(self, session_id: str, conversation_id: str) -> None:
        """设置一个客户端会话的当前对话。"""
        if self.redis is None:
            raise RuntimeError("Redis dependency is not installed")
        self.redis.setex(self._key(session_id), self.ttl_seconds, conversation_id)

    def resolve(self, session_id: str, candidate_conversation_id: str) -> str:
        """原子地复用当前对话，或在不存在时写入候选对话。"""
        if self.redis is None:
            raise RuntimeError("Redis dependency is not installed")
        key = self._key(session_id)
        for _ in range(3):
            created = self.redis.set(
                key,
                candidate_conversation_id,
                nx=True,
                ex=self.ttl_seconds,
            )
            if created:
                return candidate_conversation_id
            current = self.redis.get(key)
            if current is not None:
                self.redis.expire(key, self.ttl_seconds)
                return current
        raise RuntimeError("conversation session changed too frequently")

    def clear(self, session_id: str) -> None:
        """清除当前对话，使下一次单条请求创建新对话。"""
        if self.redis is None:
            raise RuntimeError("Redis dependency is not installed")
        self.redis.delete(self._key(session_id))
