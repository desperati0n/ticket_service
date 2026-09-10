"""Ticket tool facade that dispatches every operation through Redis."""

from __future__ import annotations

from typing import Any, Protocol
import uuid


class Queue(Protocol):
    def enqueue(self, task_id: str, operation: str, payload: dict[str, Any]) -> str: ...
    def get_task(self, task_id: str) -> dict[str, Any] | None: ...
    def wait_for_terminal(
        self,
        task_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any] | None: ...


class IdGenerator(Protocol):
    def next_id(self) -> int: ...


def _queue_result(
    ok: bool,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
    ticket_id: int | None = None,
    status: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if task_id is not None:
        data["task_id"] = task_id
    if ticket_id is not None:
        data["ticket_id"] = ticket_id
    if status is not None:
        data["status"] = status
    return {"ok": ok, "code": code, "message": message, "data": data, "retryable": retryable}


class QueuedTicketService:
    """Expose the TicketService interface while keeping databases behind the queue."""

    def __init__(
        self,
        queue: Queue,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
        id_generator: IdGenerator,
    ):
        self.queue = queue
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.id_generator = id_generator

    def _dispatch(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        pending_ticket_id: int | None = None,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        try:
            self.queue.enqueue(task_id, operation, payload)
            task = self.queue.wait_for_terminal(
                task_id,
                timeout_seconds=self.timeout_seconds,
                poll_interval_seconds=self.poll_interval_seconds,
            )
        except Exception:
            return _queue_result(
                False,
                "QUEUE_UNAVAILABLE",
                "工单任务队列暂时不可用",
                task_id=task_id if pending_ticket_id is None else None,
                ticket_id=pending_ticket_id,
                status="not_queued" if pending_ticket_id is not None else None,
                retryable=True,
            )
        return self._task_to_result(task_id, task, pending_ticket_id=pending_ticket_id)

    @staticmethod
    def _task_to_result(
        task_id: str,
        task: dict[str, Any] | None,
        *,
        pending_ticket_id: int | None = None,
    ) -> dict[str, Any]:
        if task is None or task.get("status") in {"queued", "processing"}:
            status = task.get("status", "unknown") if task else "unknown"
            pending_message = (
                "工单仍在队列中处理，请稍后使用 ticket_id 查询"
                if pending_ticket_id is not None
                else "任务仍在队列中处理，请使用 get_task_result 查询，不要重复提交写操作"
            )
            return _queue_result(
                False,
                "TASK_PENDING",
                pending_message,
                task_id=task_id if pending_ticket_id is None else None,
                ticket_id=pending_ticket_id,
                status=status,
                retryable=True,
            )
        if task.get("status") == "failed":
            return _queue_result(
                False,
                "BACKEND_FAILED",
                "后端处理任务失败",
                task_id=task_id if pending_ticket_id is None else None,
                ticket_id=pending_ticket_id,
                status="failed",
                retryable=True,
            )
        result = dict(task["result"])
        return result

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        task_id = task_id.strip()
        if not task_id:
            return _queue_result(False, "TOOL_INPUT_INVALID", "task_id 不能为空", retryable=True)
        try:
            task = self.queue.get_task(task_id)
        except Exception:
            return _queue_result(
                False,
                "QUEUE_UNAVAILABLE",
                "工单任务队列暂时不可用",
                task_id=task_id,
                retryable=True,
            )
        if task is None:
            return _queue_result(
                False,
                "TASK_NOT_FOUND",
                "任务不存在或结果已经过期",
                task_id=task_id,
                retryable=True,
            )
        return self._task_to_result(task_id, task)

    def verify_employee(self, employee_no: str) -> dict[str, Any]:
        return self._dispatch("verify_employee", {"employee_no": employee_no})

    def verify_employee_asset(self, employee_no: str, asset_description: str) -> dict[str, Any]:
        return self._dispatch(
            "verify_employee_asset",
            {"employee_no": employee_no, "asset_description": asset_description},
        )

    def create_ticket(
        self,
        employee_no: str,
        asset_description: str,
        problem_description: str,
        request_id: str,
    ) -> dict[str, Any]:
        ticket_id = self.id_generator.next_id()
        return self._dispatch(
            "create_ticket",
            {
                "ticket_id": ticket_id,
                "employee_no": employee_no,
                "asset_description": asset_description,
                "problem_description": problem_description,
                "request_id": request_id,
            },
            pending_ticket_id=ticket_id,
        )

    def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        return self._dispatch("get_ticket", {"ticket_id": ticket_id})

    def list_tickets(self, employee_no: str | None = None, limit: int = 50) -> dict[str, Any]:
        return self._dispatch("list_tickets", {"employee_no": employee_no, "limit": limit})

    def update_ticket(
        self,
        ticket_id: int,
        issue: str | None = None,
        status: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._dispatch(
            "update_ticket",
            {"ticket_id": ticket_id, "issue": issue, "status": status, "request_id": request_id},
        )

    def delete_ticket(
        self,
        ticket_id: int,
        confirmed: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._dispatch(
            "delete_ticket",
            {"ticket_id": ticket_id, "confirmed": confirmed, "request_id": request_id},
        )
