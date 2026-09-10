"""Snowflake ID generation reused from the original ticket service."""

import threading
import time


class Snowflake:
    """Generate unique numeric IDs within one process."""

    def __init__(self, worker_id: int = 1):
        if not 0 <= worker_id < 32:
            raise ValueError("worker_id must be between 0 and 31")
        self.worker_id = worker_id
        self._last_ms = -1
        self._sequence = 0
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            now = int(time.time() * 1000)
            if now == self._last_ms:
                self._sequence = (self._sequence + 1) & 0xFFF
                if self._sequence == 0:
                    while now <= self._last_ms:
                        now = int(time.time() * 1000)
            else:
                self._sequence = 0
            self._last_ms = now
            return ((now - 1704067200000) << 17) | (self.worker_id << 12) | self._sequence
