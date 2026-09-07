"""后台工单任务 Worker。运行：python worker.py"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.agent import AgentRequest, TicketAgent
from app.queue import TaskQueue
from app.real_repositories import MongoRepository, MySQLRepository
from app.schemas import TicketRequest
from app.service import TicketFlow

load_dotenv(Path(__file__).resolve().parent / ".env")


def process_message(
    message_id: str,
    fields: dict[str, str],
    *,
    queue: Any,
    agent: TicketAgent,
    mongo: Any,
    flow: TicketFlow | None = None,
) -> None:
    """按任务类型执行 Agent 或结构化流程，并保存完整响应。"""
    task_id = fields.get("task_id", "")
    updater = getattr(mongo, "update_task", None)
    event_appender = getattr(mongo, "append_task_event", None)
    getter = getattr(mongo, "get_task", None)
    events: list[dict[str, Any]] = []
    try:
        payload = json.loads(fields["payload"])
        task_type = payload.pop("task_type", "agent")
        existing = getter(task_id) if getter is not None else None
        if existing is not None and existing.get("status") in {"success", "failed"}:
            return
        result_getter = getattr(mongo, "get_agent_result", None)
        completed_agent = result_getter(task_id) if task_type == "agent" and result_getter is not None else None
        if completed_agent is not None:
            if updater is not None:
                updater(
                    task_id,
                    status=completed_agent["status"],
                    ticket_id=completed_agent.get("ticket_id"),
                    answer=completed_agent.get("assistant_message"),
                    events=completed_agent.get("events") or [],
                    error=completed_agent.get("error"),
                )
            return
        if updater is not None:
            updater(task_id, status="processing", events=[])

        if task_type == "structured":
            if flow is None:
                raise RuntimeError("structured task requires TicketFlow")
            event_stream = flow.run(TicketRequest(**payload))
        elif task_type == "agent":
            event_stream = agent.run(AgentRequest(**payload))
        else:
            raise ValueError(f"unsupported task type: {task_type}")
        for event in event_stream:
            events.append(event)
            if event_appender is not None:
                event_appender(task_id, event)
            elif updater is not None:
                updater(task_id, events=list(events))
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
    mysql = MySQLRepository()
    mongo = MongoRepository()
    queue = TaskQueue()
    agent = TicketAgent(mysql, mongo)
    flow = TicketFlow(mysql, mongo)
    consumer = os.getenv("REDIS_CONSUMER_NAME", socket.gethostname())
    while True:
        for message_id, fields in queue.consume(consumer):
            try:
                conversation_id = json.loads(fields["payload"]).get("conversation_id")
            except (KeyError, TypeError, json.JSONDecodeError):
                conversation_id = None
            with queue.maintain_ownership(message_id, consumer):
                with queue.serialize_conversation(conversation_id):
                    process_message(
                        message_id,
                        fields,
                        queue=queue,
                        agent=agent,
                        mongo=mongo,
                        flow=flow,
                    )


if __name__ == "__main__":
    run_worker()
