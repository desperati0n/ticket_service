from ticket_mcp.queued_service import QueuedTicketService


class FakeQueue:
    def __init__(self, terminal=None):
        self.terminal = terminal
        self.enqueued = []
        self.tasks = {}

    def enqueue(self, task_id, operation, payload):
        self.enqueued.append((task_id, operation, payload))
        return "1-0"

    def wait_for_terminal(self, task_id, *, timeout_seconds, poll_interval_seconds):
        return self.terminal

    def get_task(self, task_id):
        return self.tasks.get(task_id)


class FakeIds:
    def __init__(self, value=987654321):
        self.value = value

    def next_id(self):
        return self.value


def make_service(queue):
    return QueuedTicketService(
        queue,
        timeout_seconds=3,
        poll_interval_seconds=0.01,
        id_generator=FakeIds(),
    )


def test_tool_operation_is_dispatched_through_queue():
    queue = FakeQueue(
        terminal={
            "status": "success",
            "result": {
                "ok": True,
                "code": "EMPLOYEE_VERIFIED",
                "message": "ok",
                "data": {"employee_no": "10086"},
                "retryable": False,
            },
        }
    )
    service = make_service(queue)

    result = service.verify_employee("10086")

    task_id, operation, payload = queue.enqueued[0]
    assert operation == "verify_employee"
    assert payload == {"employee_no": "10086"}
    assert result["ok"] is True
    assert "task_id" not in result["data"]
    assert task_id


def test_create_preallocates_snowflake_id_and_returns_it_on_timeout():
    queue = FakeQueue(terminal={"status": "processing"})
    service = QueuedTicketService(
        queue,
        timeout_seconds=0,
        poll_interval_seconds=0,
        id_generator=FakeIds(),
    )

    result = service.create_ticket("10086", "Dell", "黑屏", "request-1")

    assert result["code"] == "TASK_PENDING"
    assert result["data"]["status"] == "processing"
    assert result["data"]["ticket_id"] == 987654321
    assert "task_id" not in result["data"]
    assert queue.enqueued[0][2]["ticket_id"] == 987654321
    assert len(queue.enqueued) == 1


def test_get_task_result_returns_original_business_result():
    queue = FakeQueue()
    queue.tasks["task-1"] = {
        "status": "success",
        "result": {
            "ok": True,
            "code": "TICKET_CREATED",
            "message": "created",
            "data": {"ticket": {"id": 9}},
            "retryable": False,
        },
    }
    service = make_service(queue)

    result = service.get_task_result("task-1")

    assert result["code"] == "TICKET_CREATED"
    assert "task_id" not in result["data"]
