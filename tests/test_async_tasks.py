"""异步任务入队和 Worker 消费测试。"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.queue import TaskQueue
from worker import process_message


class FakeQueue:
    def __init__(self):
        self.enqueued = []
        self.acked = []

    def enqueue(self, task_id, payload):
        self.enqueued.append((task_id, payload))
        return "1-0"

    def acknowledge(self, message_id):
        self.acked.append(message_id)
        return 1


class CompletingQueue(FakeQueue):
    """入队时立即写入模拟 Worker 结果，避免 SSE 接口测试等待。"""

    def __init__(self, mongo):
        super().__init__()
        self.mongo = mongo

    def enqueue(self, task_id, payload):
        message_id = super().enqueue(task_id, payload)
        self.mongo.update_task(
            task_id,
            status="success",
            answer="报修已提交。",
            events=[
                {
                    "step": "answer",
                    "status": "success",
                    "data": {"message": "报修已提交。"},
                    "request_id": task_id,
                    "conversation_id": payload["conversation_id"],
                },
                {
                    "step": "done",
                    "status": "success",
                    "data": {"success": True, "ticket_id": 123},
                    "request_id": task_id,
                    "conversation_id": payload["conversation_id"],
                },
            ],
        )
        return message_id


class FakeTaskMongo:
    def __init__(self):
        self.tasks = {}
        self.appended_events = []

    def create_task(self, task_id, payload):
        task = {"task_id": task_id, "input": payload, "status": "queued", "events": []}
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def update_task(self, task_id, **fields):
        self.tasks[task_id].update(fields)

    def append_task_event(self, task_id, event):
        self.tasks[task_id]["events"].append(event)
        self.appended_events.append(event)


class FakeAgent:
    def __init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        yield {
            "step": "answer",
            "status": "success",
            "data": {"message": "报修已提交，工单状态为待处理。"},
        }
        yield {"step": "done", "status": "success", "data": {"success": True, "ticket_id": 123}}


class FakeRedisStream:
    def __init__(self, *, claimed=None, new_rows=None):
        self.claimed = claimed or []
        self.new_rows = new_rows or []
        self.read_calls = []
        self.claim_calls = []

    def xgroup_create(self, *args, **kwargs):
        return True

    def xautoclaim(self, *args, **kwargs):
        return ["0-0", self.claimed, []]

    def xreadgroup(self, *args, **kwargs):
        self.read_calls.append((args, kwargs))
        return self.new_rows

    def xclaim(self, *args, **kwargs):
        self.claim_calls.append((args, kwargs))
        return []


def _task_queue_with(redis):
    queue = TaskQueue.__new__(TaskQueue)
    queue.redis = redis
    queue.stream_name = "ticket_tasks"
    queue.group_name = "ticket_workers"
    queue.pending_idle_ms = 120000
    queue.heartbeat_interval_seconds = 30
    return queue


def test_single_task_endpoint_streams_chat_timeline(monkeypatch):
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)

    response = TestClient(app).post("/ticket/task", json={"message": "显示器坏了，工号 10086"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: queued" in response.text
    assert "event: answer" in response.text
    assert "event: done" in response.text
    assert len(queue.enqueued) == 1


def test_task_endpoint_always_uses_a_fresh_conversation(monkeypatch):
    """每个异步任务都应刷新上下文，不能沿用调用方提供的旧会话 ID。"""
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)

    response = TestClient(app).post(
        "/ticket/task",
        json=[{"message": "新的独立报修", "conversation_id": "old-conversation"}],
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert queue.enqueued[0][1]["conversation_id"] != "old-conversation"


def test_task_endpoint_accepts_batch_and_streams_each_timeline(monkeypatch):
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)

    response = TestClient(app).post(
        "/ticket/task",
        json=[
            {"message": "显示器坏了，工号 10001"},
            {"message": "打印机卡纸，工号 10005"},
            {"message": "笔记本无法开机，工号 10006"},
        ],
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: queued") == 3
    assert response.text.count("event: answer") == 3
    assert response.text.count("event: done") == 3
    assert len(queue.enqueued) == 3
    assert len({task_id for task_id, _ in queue.enqueued}) == 3
    assert all(task_id.isdigit() for task_id, _ in queue.enqueued)
    streamed_events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    streamed_chat_events = [event for event in streamed_events if event["step"] != "queued"]
    original_chat_events = [
        event
        for task_id, _ in queue.enqueued
        for event in mongo.get_task(task_id)["events"]
    ]
    assert streamed_chat_events == original_chat_events


def test_task_endpoint_rejects_empty_batch(monkeypatch):
    import app.main as app_main

    monkeypatch.setattr(app_main, "task_queue", FakeQueue())
    monkeypatch.setattr(app_main, "mongo_repository", FakeTaskMongo())

    response = TestClient(app).post("/ticket/task", json=[])

    assert response.status_code == 422


def test_task_endpoint_does_not_hardcode_batch_size_limit(monkeypatch):
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)
    requests = [{"message": f"第 {index} 条报修"} for index in range(101)]

    response = TestClient(app).post("/ticket/task", json=requests)

    assert response.status_code == 200
    assert response.text.count("event: queued") == 101
    assert response.text.count("event: done") == 101
    assert len(queue.enqueued) == 101


def test_worker_processes_task_and_acknowledges_message():
    queue = FakeQueue()
    mongo = FakeTaskMongo()
    agent = FakeAgent()
    mongo.create_task("task-1", {"message": "显示器坏了", "request_id": "task-1"})

    process_message(
        "redis-1",
        {"task_id": "task-1", "payload": '{"message": "显示器坏了", "request_id": "task-1"}'},
        queue=queue,
        agent=agent,
        mongo=mongo,
    )

    task = mongo.get_task("task-1")
    assert task["status"] == "success"
    assert task["ticket_id"] == 123
    assert task["answer"] == "报修已提交，工单状态为待处理。"
    assert [event["step"] for event in task["events"]] == ["answer", "done"]
    assert [event["step"] for event in mongo.appended_events] == ["answer", "done"]
    assert agent.requests[0].message == "显示器坏了"
    assert queue.acked == ["redis-1"]


def test_worker_acknowledges_already_completed_reclaimed_task_without_rerun():
    queue = FakeQueue()
    mongo = FakeTaskMongo()
    agent = FakeAgent()
    mongo.create_task("task-1", {"message": "显示器坏了"})
    mongo.update_task("task-1", status="success", ticket_id=123)

    process_message(
        "redis-pending-1",
        {"task_id": "task-1", "payload": '{"message": "显示器坏了"}'},
        queue=queue,
        agent=agent,
        mongo=mongo,
    )

    assert agent.requests == []
    assert queue.acked == ["redis-pending-1"]


def test_queue_reclaims_stale_pending_message_before_reading_new_work():
    pending = [("1-0", {"task_id": "task-1", "payload": "{}"})]
    redis = FakeRedisStream(claimed=pending)
    queue = _task_queue_with(redis)

    assert queue.consume("worker-2") == pending
    assert redis.read_calls == []


def test_queue_reads_new_work_when_no_stale_pending_message_exists():
    rows = [("ticket_tasks", [("2-0", {"task_id": "task-2", "payload": "{}"})])]
    redis = FakeRedisStream(new_rows=rows)
    queue = _task_queue_with(redis)

    assert queue.consume("worker-2") == rows[0][1]
    assert len(redis.read_calls) == 1


def test_queue_touch_refreshes_message_for_current_consumer():
    redis = FakeRedisStream()
    queue = _task_queue_with(redis)

    queue.touch("1-0", "worker-3")

    _, kwargs = redis.claim_calls[0]
    assert kwargs["min_idle_time"] == 0
    assert kwargs["message_ids"] == ["1-0"]
    assert kwargs["justid"] is True


def test_compose_starts_multiple_workers_after_database_migration():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "scale: ${WORKER_REPLICAS:-4}" in compose
    assert "restart: unless-stopped" in compose
    assert "mysql-migrate:" in compose
    assert compose.count("condition: service_completed_successfully") == 2


def test_task_status_returns_chat_events_and_answer(monkeypatch):
    """状态查询应返回 Worker 保存的 Chat Agent 最终回复和完整事件。"""
    import app.main as app_main

    mongo = FakeTaskMongo()
    mongo.create_task("task-2", {"message": "显示器坏了"})
    mongo.update_task(
        "task-2",
        status="success",
        ticket_id=123,
        answer="报修已提交。",
        events=[{"step": "answer", "status": "success", "data": {"message": "报修已提交。"}}],
    )
    monkeypatch.setattr(app_main, "mongo_repository", mongo)

    response = TestClient(app).get("/ticket/task/task-2")

    assert response.status_code == 200
    assert response.json()["answer"] == "报修已提交。"
    assert response.json()["events"][0]["step"] == "answer"
