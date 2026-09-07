"""异步任务入队和 Worker 消费测试。"""

from fastapi.testclient import TestClient

from app.main import app
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


class FakeTaskMongo:
    def __init__(self):
        self.tasks = {}

    def create_task(self, task_id, payload):
        task = {"task_id": task_id, "input": payload, "status": "queued"}
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def update_task(self, task_id, **fields):
        self.tasks[task_id].update(fields)


class FakeAgent:
    def run(self, request):
        yield {"step": "done", "status": "success", "data": {"success": True, "ticket_id": 123}}


def test_task_endpoint_returns_immediately_after_enqueue(monkeypatch):
    import app.main as app_main

    queue = FakeQueue()
    mongo = FakeTaskMongo()
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)

    response = TestClient(app).post("/ticket/task", json={"message": "显示器坏了，工号 10086"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["task_id"].isdigit()
    assert len(queue.enqueued) == 1
    assert mongo.get_task(body["task_id"])["status"] == "queued"


def test_task_endpoint_accepts_batch_and_enqueues_each_item(monkeypatch):
    import app.main as app_main

    queue = FakeQueue()
    mongo = FakeTaskMongo()
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

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["total"] == 3
    assert len(body["tasks"]) == 3
    assert len(queue.enqueued) == 3
    assert len({task["task_id"] for task in body["tasks"]}) == 3
    assert all(task["task_id"].isdigit() for task in body["tasks"])
    assert all(mongo.get_task(task["task_id"])["status"] == "queued" for task in body["tasks"])


def test_task_endpoint_rejects_empty_batch(monkeypatch):
    import app.main as app_main

    monkeypatch.setattr(app_main, "task_queue", FakeQueue())
    monkeypatch.setattr(app_main, "mongo_repository", FakeTaskMongo())

    response = TestClient(app).post("/ticket/task", json=[])

    assert response.status_code == 422


def test_worker_processes_task_and_acknowledges_message():
    queue = FakeQueue()
    mongo = FakeTaskMongo()
    mongo.create_task("task-1", {"message": "显示器坏了", "request_id": "task-1"})

    process_message(
        "redis-1",
        {"task_id": "task-1", "payload": '{"message": "显示器坏了", "request_id": "task-1"}'},
        queue=queue,
        agent=FakeAgent(),
        mongo=mongo,
    )

    assert mongo.get_task("task-1")["status"] == "success"
    assert mongo.get_task("task-1")["ticket_id"] == 123
    assert queue.acked == ["redis-1"]
