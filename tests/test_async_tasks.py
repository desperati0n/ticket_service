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
    assert body["total"] == 1
    assert len(body["tasks"]) == 1
    task = body["tasks"][0]
    assert task["task_id"].isdigit()
    assert len(queue.enqueued) == 1
    assert mongo.get_task(task["task_id"])["status"] == "queued"


def test_task_endpoint_always_uses_a_fresh_conversation(monkeypatch):
    """每个异步任务都应刷新上下文，不能沿用调用方提供的旧会话 ID。"""
    import app.main as app_main

    queue = FakeQueue()
    mongo = FakeTaskMongo()
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)

    response = TestClient(app).post(
        "/ticket/task",
        json={"message": "新的独立报修", "conversation_id": "old-conversation"},
    )

    task = response.json()["tasks"][0]
    assert task["conversation_id"] != "old-conversation"
    assert queue.enqueued[0][1]["conversation_id"] == task["conversation_id"]


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


def test_task_endpoint_does_not_hardcode_batch_size_limit(monkeypatch):
    import app.main as app_main

    queue = FakeQueue()
    mongo = FakeTaskMongo()
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)
    requests = [{"message": f"第 {index} 条报修"} for index in range(101)]

    response = TestClient(app).post("/ticket/task", json=requests)

    assert response.status_code == 202
    assert response.json()["total"] == 101
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
    assert agent.requests[0].message == "显示器坏了"
    assert queue.acked == ["redis-1"]


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
