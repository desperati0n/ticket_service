"""为接口测试提供仅存在于测试代码中的仓储替身。"""

from datetime import datetime, timezone

import pytest

from app.ids import Snowflake
from app.models import Asset, Employee
from app.service import TicketFlow


class FakeMySQL:
    """测试专用的 MySQL 替身，不属于生产存储实现。"""

    def __init__(self):
        self._id = Snowflake()
        self.employees = {"10086": Employee(10086, "10086", "张三", "研发部")}
        self.assets = [Asset(1, "A-001", "Dell 显示器")]
        self.employee_assets = {10086: {1}}
        self.tickets = []

    def get_employee_by_no(self, employee_no):
        return self.employees.get(str(employee_no))

    def verify_asset_belongs_to_employee(self, description, employee_id):
        description = description.lower()
        asset_ids = self.employee_assets.get(employee_id, set())
        return next((asset for asset in self.assets if asset.id in asset_ids and description in asset.name.lower()), None)

    def create_ticket(self, *, employee, asset, issue, request_id=None):
        if request_id is not None:
            existing = next((ticket for ticket in self.tickets if ticket.get("request_id") == request_id), None)
            if existing is not None:
                return existing
        ticket = {"id": self._id.next_id(), "employee_id": employee.id, "asset_id": asset.id if asset else None,
                  "request_id": request_id, "issue": issue, "status": "PENDING",
                  "created_at": datetime.now(timezone.utc).isoformat()}
        self.tickets.append(ticket)
        return ticket

    def get_ticket(self, ticket_id):
        return next((ticket for ticket in self.tickets if ticket["id"] == ticket_id), None)

    def list_tickets(self, employee_no=None):
        if employee_no is None:
            return list(reversed(self.tickets))
        employee = self.get_employee_by_no(employee_no)
        return list(reversed([ticket for ticket in self.tickets if employee and ticket["employee_id"] == employee.id]))

    def update_ticket(self, ticket_id, *, issue=None, status=None):
        ticket = self.get_ticket(ticket_id)
        if ticket and issue is not None:
            ticket["issue"] = issue
        if ticket and status is not None:
            ticket["status"] = status
        return ticket

    def delete_ticket(self, ticket_id):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return False
        self.tickets.remove(ticket)
        return True


class FakeMongo:
    """测试专用的 MongoDB 替身。"""

    def __init__(self):
        self.logs = []
        self.tasks = {}

    def start_log(self, request_id, payload):
        log = {"request_id": request_id, "input": payload, "steps": [], "status": "started"}
        self.logs.append(log)
        return log

    def append_step(self, log, step):
        log["steps"].append(step)

    def finish_log(self, log, *, status, ticket_id=None, error=None):
        log.update({"status": status, "ticket_id": ticket_id})
        if error:
            log["error"] = error

    def create_task(self, task_id, payload):
        task = {"kind": "async_task", "task_id": task_id, "input": payload, "status": "queued", "events": []}
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def get_tasks(self, task_ids):
        return {task_id: self.tasks[task_id] for task_id in task_ids if task_id in self.tasks}

    def update_task(self, task_id, **fields):
        self.tasks[task_id].update(fields)

    def append_task_event(self, task_id, event):
        self.tasks[task_id]["events"].append(event)


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


@pytest.fixture
def repositories(monkeypatch):
    """将当前测试请求切换到测试替身，避免依赖外部数据库。"""
    import app.main as app_main

    mysql = FakeMySQL()
    mongo = FakeMongo()
    monkeypatch.setattr(app_main, "mysql_repository", mysql)
    monkeypatch.setattr(app_main, "mongo_repository", mongo)
    monkeypatch.setattr(app_main, "flow", TicketFlow(mysql, mongo))
    monkeypatch.setattr(app_main, "conversation_sessions", FakeConversationSessions())

    class ImmediateQueue:
        def __init__(self):
            self.acked = []

        def enqueue(self, task_id, payload):
            import json

            from worker import process_message

            process_message(
                f"redis-{task_id}",
                {"task_id": task_id, "payload": json.dumps(payload, ensure_ascii=False)},
                queue=self,
                agent=app_main.ticket_agent,
                mongo=app_main.mongo_repository,
                flow=app_main.flow,
            )
            return f"redis-{task_id}"

        def acknowledge(self, message_id):
            self.acked.append(message_id)
            return 1

    monkeypatch.setattr(app_main, "task_queue", ImmediateQueue())
    import app.cli as app_cli

    monkeypatch.setattr(app_cli, "flow", app_main.flow)
    return mysql, mongo

