"""Redis queue consumer that owns database access and business execution."""

from __future__ import annotations

import json
import socket
from typing import Any

from .config import Settings
from .queue import RedisTicketQueue, TERMINAL_STATES
from .repositories import MongoAuditRepository, MySQLRepository
from .service import TicketService


OPERATIONS = {
    "verify_employee",
    "verify_employee_asset",
    "create_ticket",
    "get_ticket",
    "list_tickets",
    "update_ticket",
    "delete_ticket",
}


def process_message(
    message_id: str,
    fields: dict[str, str],
    *,
    queue: Any,
    service: TicketService,
) -> None:
    """Execute one allowlisted operation and ACK only after recording a terminal state."""
    task_id = fields.get("task_id", "")
    terminal_written = False
    try:
        existing = queue.get_task(task_id) if task_id else None
        if existing is not None and existing.get("status") in TERMINAL_STATES:
            terminal_written = True
            return
        operation = fields["operation"]
        if operation not in OPERATIONS:
            raise ValueError(f"unsupported operation: {operation}")
        payload = json.loads(fields["payload"])
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        queue.mark_processing(task_id)
        result = getattr(service, operation)(**payload)
        queue.complete(task_id, result)
        terminal_written = True
    except Exception as exc:
        if task_id:
            queue.fail(task_id, f"backend execution failed: {exc}")
            terminal_written = True
    finally:
        if terminal_written:
            queue.acknowledge(message_id)


def main() -> None:
    settings = Settings.from_env()
    queue = RedisTicketQueue(settings)
    service = TicketService(MySQLRepository(settings), MongoAuditRepository(settings))
    consumer_name = socket.gethostname()
    while True:
        for message_id, fields in queue.consume(consumer_name):
            with queue.maintain_ownership(message_id, consumer_name):
                process_message(message_id, fields, queue=queue, service=service)


if __name__ == "__main__":
    main()
