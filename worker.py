"""后台工单任务 Worker。运行：python worker.py"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.agent import AgentRequest, TicketAgent
from app.ids import Snowflake
from app.queue import TaskQueue
from app.real_repositories import MongoRepository, MySQLRepository

load_dotenv(Path(__file__).resolve().parent / ".env")


def process_message(message_id: str, fields: dict[str, str], *, queue: Any, agent: TicketAgent, mongo: Any) -> None:
    """复用 Chat Agent 处理消息，保存完整响应并在终态确认消息。"""
    task_id = fields["task_id"]
    payload = json.loads(fields["payload"])
    updater = getattr(mongo, "update_task", None)
    if updater is not None:
        updater(task_id, status="processing", events=[])
    events: list[dict[str, Any]] = []
    try:
        events = list(agent.run(AgentRequest(**payload)))
        answer_event = next((event for event in reversed(events) if event.get("step") == "answer"), {})
        answer_data = answer_event.get("data") or {}
        answer = answer_data.get("message")
        done = next((event for event in reversed(events) if event.get("step") == "done"), {})
        data = done.get("data") or {}
        if done.get("status") == "success" and data.get("success"):
            if updater is not None:
                updater(
                    task_id,
                    status="success",
                    ticket_id=data.get("ticket_id"),
                    answer=answer,
                    events=events,
                )
        else:
            error_event = next((event for event in reversed(events) if event.get("status") == "failed"), {})
            error_data = error_event.get("data") or {}
            if updater is not None:
                updater(
                    task_id,
                    status="failed",
                    answer=answer,
                    events=events,
                    error=error_data.get("message", "任务处理失败"),
                )
    except Exception as exc:
        if updater is not None:
            updater(task_id, status="failed", events=events, error=f"Worker 执行失败：{exc}")
    finally:
        queue.acknowledge(message_id)


def run_worker() -> None:
    """持续消费 Redis Stream。"""
    worker_id = int(os.getenv("SNOWFLAKE_WORKER_ID", "2"))
    mysql = MySQLRepository(Snowflake(worker_id=worker_id))
    mongo = MongoRepository()
    queue = TaskQueue()
    agent = TicketAgent(mysql, mongo)
    consumer = os.getenv("REDIS_CONSUMER_NAME", socket.gethostname())
    while True:
        for message_id, fields in queue.consume(consumer):
            process_message(message_id, fields, queue=queue, agent=agent, mongo=mongo)


if __name__ == "__main__":
    run_worker()
