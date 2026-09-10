import json

from ticket_mcp.worker import process_message


class FakeQueue:
    def __init__(self, existing=None):
        self.existing = existing
        self.processing = []
        self.completed = []
        self.failed = []
        self.acked = []

    def get_task(self, task_id):
        return self.existing

    def mark_processing(self, task_id):
        self.processing.append(task_id)

    def complete(self, task_id, result):
        self.completed.append((task_id, result))

    def fail(self, task_id, error):
        self.failed.append((task_id, error))

    def acknowledge(self, message_id):
        self.acked.append(message_id)


class FakeService:
    def __init__(self):
        self.calls = []

    def get_ticket(self, ticket_id):
        self.calls.append(ticket_id)
        return {"ok": True, "code": "TICKET_FOUND", "data": {"ticket": {"id": ticket_id}}}


def test_worker_executes_allowlisted_operation_and_then_acknowledges():
    queue = FakeQueue()
    service = FakeService()
    fields = {
        "task_id": "task-7",
        "operation": "get_ticket",
        "payload": json.dumps({"ticket_id": 7}),
    }

    process_message("1-0", fields, queue=queue, service=service)

    assert service.calls == [7]
    assert queue.processing == ["task-7"]
    assert queue.completed[0][1]["code"] == "TICKET_FOUND"
    assert queue.acked == ["1-0"]


def test_worker_does_not_repeat_a_terminal_reclaimed_task():
    queue = FakeQueue(existing={"status": "success", "result": {"ok": True}})
    service = FakeService()

    process_message(
        "1-1",
        {"task_id": "done", "operation": "get_ticket", "payload": "{}"},
        queue=queue,
        service=service,
    )

    assert service.calls == []
    assert queue.acked == ["1-1"]
