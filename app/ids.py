"""本模块提供雪花 ID 生成能力。"""

import threading
import time


class Snowflake:
    """雪花算法生成器在单进程中生成不重复的数字 ID。"""

    def __init__(self, worker_id: int = 1):
        """使用指定工作节点编号初始化生成器。"""
        if not 0 <= worker_id < 32:
            raise ValueError("worker_id must be between 0 and 31")
        self.worker_id = worker_id
        self._last_ms = -1
        self._sequence = 0
        self._lock = threading.Lock()

    def next_id(self) -> int:
        """生成并返回下一个雪花 ID。"""
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

