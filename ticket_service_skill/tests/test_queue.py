import json

from ticket_mcp.queue import RedisTicketQueue
from tests.test_mcp_server import make_settings


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.added = []
        self.claimed = []
        self.new_rows = []
        self.read_calls = []
        self.acked = []
        self.deleted = []

    def xgroup_create(self, *args, **kwargs):
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def xadd(self, stream, fields):
        self.added.append((stream, fields))
        return "1-0"

    def xautoclaim(self, *args, **kwargs):
        return ("0-0", self.claimed, [])

    def xreadgroup(self, *args, **kwargs):
        self.read_calls.append((args, kwargs))
        return [("ticket_commands", self.new_rows)] if self.new_rows else []

    def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))
        return 1

    def xdel(self, stream, message_id):
        self.deleted.append((stream, message_id))
        return 1


def test_redis_queue_serializes_command_and_terminal_result():
    redis = FakeRedis()
    queue = RedisTicketQueue(make_settings(), redis_client=redis)

    message_id = queue.enqueue("task-1", "get_ticket", {"ticket_id": 7})

    assert message_id == "1-0"
    stream, fields = redis.added[0]
    assert stream == "ticket_commands"
    assert fields["task_id"] == "task-1"
    assert json.loads(fields["payload"]) == {"ticket_id": 7}
    assert queue.get_task("task-1")["status"] == "queued"

    queue.complete("task-1", {"ok": True, "data": {"ticket": {"id": 7}}})

    task = queue.get_task("task-1")
    assert task["status"] == "success"
    assert task["result"]["data"]["ticket"]["id"] == 7


def test_queue_reclaims_stale_work_before_reading_new_commands():
    redis = FakeRedis()
    redis.claimed = [("1-0", {"task_id": "old"})]
    redis.new_rows = [("2-0", {"task_id": "new"})]
    queue = RedisTicketQueue(make_settings(), redis_client=redis)

    rows = queue.consume("backend-1")

    assert rows == redis.claimed
    assert redis.read_calls == []


def test_queue_acknowledges_and_removes_completed_stream_message():
    redis = FakeRedis()
    queue = RedisTicketQueue(make_settings(), redis_client=redis)

    assert queue.acknowledge("1-0") == 1
    assert redis.acked == [("ticket_commands", "ticket_backends", "1-0")]
    assert redis.deleted == [("ticket_commands", "1-0")]
