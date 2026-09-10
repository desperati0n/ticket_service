"""异步任务入队和 Worker 消费测试。"""

import json
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.queue import TaskQueue
from app.real_repositories import MongoRepository
from app.session import ConversationSessionStore
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
        self.batch_reads = []

    def create_task(self, task_id, payload):
        task = {"task_id": task_id, "input": payload, "status": "queued", "events": []}
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def get_tasks(self, task_ids):
        self.batch_reads.append(list(task_ids))
        return {task_id: self.tasks[task_id] for task_id in task_ids if task_id in self.tasks}

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


class FakeConversationSessions:
    ttl_seconds = 604800

    def __init__(self):
        self.values = {}

    def get(self, session_id):
        return self.values.get(session_id)

    def set(self, session_id, conversation_id):
        self.values[session_id] = conversation_id

    def resolve(self, session_id, candidate_conversation_id):
        return self.values.setdefault(session_id, candidate_conversation_id)

    def clear(self, session_id):
        self.values.pop(session_id, None)


class FakeRedisStream:
    def __init__(self, *, claimed=None, new_rows=None):
        self.claimed = claimed or []
        self.new_rows = new_rows or []
        self.read_calls = []
        self.claim_calls = []
        self.lock_calls = []
        self.acked = []
        self.deleted = []

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

    def xack(self, stream_name, group_name, message_id):
        self.acked.append((stream_name, group_name, message_id))
        return 1

    def xdel(self, stream_name, message_id):
        self.deleted.append((stream_name, message_id))
        return 1

    def lock(self, *args, **kwargs):
        lock = FakeLock()
        self.lock_calls.append((args, kwargs, lock))
        return lock


class FakeLock:
    def __init__(self):
        self.acquired = False
        self.released = False

    def acquire(self, **kwargs):
        self.acquired = True
        return True

    def extend(self, *args, **kwargs):
        return True

    def release(self):
        self.released = True


def _task_queue_with(redis):
    queue = TaskQueue.__new__(TaskQueue)
    queue.redis = redis
    queue.stream_name = "ticket_tasks"
    queue.group_name = "ticket_workers"
    queue.pending_idle_ms = 120000
    queue.heartbeat_interval_seconds = 30
    queue.conversation_lock_timeout_seconds = 120
    queue.conversation_lock_refresh_seconds = 30
    return queue


def test_single_task_endpoint_streams_chat_timeline(monkeypatch):
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)
    monkeypatch.setattr(app_main, "conversation_sessions", FakeConversationSessions())

    response = TestClient(app).post("/ticket/task", json={"message": "显示器坏了，工号 10086"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: queued" in response.text
    assert "event: answer" in response.text
    assert "event: done" in response.text
    assert len(queue.enqueued) == 1


def test_single_task_endpoint_reuses_current_session_conversation(monkeypatch):
    """同一客户端连续发送单条 JSON 时应延续 conversation_id。"""
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)
    monkeypatch.setattr(app_main, "conversation_sessions", FakeConversationSessions())
    client = TestClient(app)

    first = client.post(
        "/ticket/task",
        json={"message": "显示器坏了", "conversation_id": "initial-conversation"},
    )
    second = client.post("/ticket/task", json={"message": "工号是 10086", "conversation_id": "ignored-old-id"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert queue.enqueued[0][1]["conversation_id"] == "initial-conversation"
    assert queue.enqueued[0][1]["conversation_id"] == queue.enqueued[1][1]["conversation_id"]


def test_task_endpoint_accepts_batch_and_streams_each_timeline(monkeypatch):
    import app.main as app_main

    mongo = FakeTaskMongo()
    queue = CompletingQueue(mongo)
    monkeypatch.setattr(app_main, "task_queue", queue)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)
    sessions = FakeConversationSessions()
    monkeypatch.setattr(app_main, "conversation_sessions", sessions)
    client = TestClient(app)

    client.post("/ticket/task", json={"message": "批量前的普通消息"})
    previous_conversation = queue.enqueued[0][1]["conversation_id"]

    response = client.post(
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
    assert any(len(task_ids) == 3 for task_ids in mongo.batch_reads)
    batch_items = queue.enqueued[1:4]
    assert len(queue.enqueued) == 4
    assert len({task_id for task_id, _ in batch_items}) == 3
    assert all(len(task_id) == 36 for task_id, _ in batch_items)
    streamed_events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    streamed_chat_events = [event for event in streamed_events if event["step"] != "queued"]
    original_chat_events = [
        event
        for task_id, _ in batch_items
        for event in mongo.get_task(task_id)["events"]
    ]
    assert streamed_chat_events == original_chat_events

    batch_conversations = [payload["conversation_id"] for _, payload in batch_items]
    assert len(set(batch_conversations)) == 3
    assert previous_conversation not in batch_conversations
    assert sessions.values == {}

    client.post(
        "/ticket/task",
        json={"message": "批量后的普通消息", "conversation_id": previous_conversation},
    )
    assert queue.enqueued[-1][1]["conversation_id"] != previous_conversation


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
    monkeypatch.setattr(app_main, "conversation_sessions", FakeConversationSessions())
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


def test_worker_routes_structured_ticket_task_to_ticket_flow():
    queue = FakeQueue()
    mongo = FakeTaskMongo()
    agent = FakeAgent()

    class Flow:
        def __init__(self):
            self.requests = []

        def run(self, request):
            self.requests.append(request)
            yield {"step": "done", "status": "success", "data": {"success": True, "ticket_id": 456}}

    flow = Flow()
    mongo.create_task("task-2", {"employee_no": "10086"})

    process_message(
        "redis-structured-1",
        {
            "task_id": "task-2",
            "payload": json.dumps(
                {
                    "task_type": "structured",
                    "employee_no": "10086",
                    "asset_description": "Dell 显示器",
                    "problem_description": "无法点亮",
                    "request_id": "task-2",
                },
                ensure_ascii=False,
            ),
        },
        queue=queue,
        agent=agent,
        mongo=mongo,
        flow=flow,
    )

    assert agent.requests == []
    assert flow.requests[0].employee_no == "10086"
    assert mongo.get_task("task-2")["status"] == "success"
    assert queue.acked == ["redis-structured-1"]


def test_worker_recovers_finished_agent_log_without_rerunning_model():
    queue = FakeQueue()

    class Mongo(FakeTaskMongo):
        def get_agent_result(self, request_id):
            return {
                "status": "success",
                "ticket_id": 789,
                "assistant_message": "此前已经处理完成",
                "events": [{"step": "done", "status": "success", "data": {"success": True}}],
            }

    mongo = Mongo()
    agent = FakeAgent()
    mongo.create_task("task-3", {"message": "显示器坏了"})

    process_message(
        "redis-reclaimed-3",
        {"task_id": "task-3", "payload": '{"task_type":"agent","message":"显示器坏了"}'},
        queue=queue,
        agent=agent,
        mongo=mongo,
    )

    task = mongo.get_task("task-3")
    assert agent.requests == []
    assert task["status"] == "success"
    assert task["ticket_id"] == 789
    assert queue.acked == ["redis-reclaimed-3"]


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


def test_queue_removes_message_after_successful_acknowledgement():
    redis = FakeRedisStream()
    queue = _task_queue_with(redis)

    assert queue.acknowledge("1-0") == 1
    assert redis.acked == [("ticket_tasks", "ticket_workers", "1-0")]
    assert redis.deleted == [("ticket_tasks", "1-0")]


def test_queue_serializes_each_conversation_with_a_distributed_lock():
    redis = FakeRedisStream()
    queue = _task_queue_with(redis)

    with queue.serialize_conversation("conversation-1"):
        assert redis.lock_calls[0][2].acquired is True

    args, kwargs, lock = redis.lock_calls[0]
    assert args[0].startswith("ticket_conversation_lock:")
    assert kwargs["thread_local"] is False
    assert lock.released is True


def test_conversation_session_store_persists_refreshes_and_clears_mapping():
    class Redis:
        def __init__(self):
            self.values = {}
            self.expired = []

        def get(self, key):
            return self.values.get(key)

        def setex(self, key, ttl, value):
            self.values[key] = value

        def set(self, key, value, **options):
            if options.get("nx") and key in self.values:
                return None
            self.values[key] = value
            return True

        def expire(self, key, ttl):
            self.expired.append((key, ttl))

        def delete(self, key):
            self.values.pop(key, None)

    redis = Redis()
    store = ConversationSessionStore.__new__(ConversationSessionStore)
    store.redis = redis
    store.ttl_seconds = 60

    store.set("session-1", "conversation-1")
    assert store.resolve("session-1", "conversation-2") == "conversation-1"
    assert store.get("session-1") == "conversation-1"
    assert redis.expired == [
        ("ticket_session:session-1:conversation", 60),
        ("ticket_session:session-1:conversation", 60),
    ]
    store.clear("session-1")
    assert store.get("session-1") is None


def test_mongo_task_creation_is_idempotent_and_indexes_are_initialized_once():
    class Collection:
        def __init__(self):
            self.indexes = []
            self.task = None

        def create_index(self, fields, **options):
            self.indexes.append((fields, options))

        def update_one(self, query, update, upsert=False):
            if self.task is None:
                self.task = update["$setOnInsert"]

        def find_one(self, query, projection):
            return self.task

    repository = MongoRepository.__new__(MongoRepository)
    repository.collection = Collection()
    repository._indexes_ready = False
    repository._index_lock = threading.Lock()

    first = repository.create_task("task-1", {"message": "第一次"})
    retried = repository.create_task("task-1", {"message": "重试"})

    assert first["input"]["message"] == "第一次"
    assert retried["input"]["message"] == "第一次"
    assert len(repository.collection.indexes) == 3


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
