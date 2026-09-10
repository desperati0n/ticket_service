from copy import deepcopy

from ticket_mcp.models import Asset, Employee
from ticket_mcp.service import TicketService


class FakeTickets:
    def __init__(self):
        self.employees = {
            "10086": Employee(10086, "10086", "张三", "研发部"),
            "99999": Employee(99999, "99999", "离职员工", "研发部", "inactive"),
        }
        self.assets = {
            10086: [
                Asset(20001, "MON-001", "Dell 显示器"),
                Asset(20003, "LAP-001", "Dell 笔记本"),
            ]
        }
        self.tickets = {}
        self.request_ids = {}

    def get_employee_by_no(self, employee_no):
        return self.employees.get(employee_no)

    def find_employee_assets(self, employee_id, query):
        query = query.lower()
        return [
            asset
            for asset in self.assets.get(employee_id, [])
            if query in asset.name.lower()
            or query in asset.asset_code.lower()
            or asset.name.lower() in query
        ]

    def create_ticket(self, *, ticket_id, employee_no, asset_id, issue, request_id):
        if request_id in self.request_ids:
            ticket = self.tickets[self.request_ids[request_id]]
            if ticket["employee_no"] != employee_no or ticket["asset_id"] != asset_id or ticket["issue"] != issue:
                raise ValueError("conflict")
            return deepcopy(ticket), False
        ticket = {
            "id": ticket_id,
            "request_id": request_id,
            "employee_no": employee_no,
            "asset_id": asset_id,
            "issue": issue,
            "status": "PENDING",
        }
        self.tickets[ticket_id] = ticket
        self.request_ids[request_id] = ticket_id
        return deepcopy(ticket), True

    def get_ticket(self, ticket_id):
        ticket = self.tickets.get(ticket_id)
        return deepcopy(ticket) if ticket else None

    def list_tickets(self, employee_no, limit):
        rows = list(self.tickets.values())
        if employee_no:
            rows = [row for row in rows if row["employee_no"] == employee_no]
        return deepcopy(rows[:limit])

    def update_ticket(self, ticket_id, *, issue, status):
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return None
        if issue is not None:
            ticket["issue"] = issue
        if status is not None:
            ticket["status"] = status
        return deepcopy(ticket)

    def delete_ticket(self, ticket_id):
        return self.tickets.pop(ticket_id, None) is not None


class FakeAudit:
    def __init__(self):
        self.records = []

    def record(self, **record):
        self.records.append(record)
        return True


def make_service():
    tickets = FakeTickets()
    audit = FakeAudit()
    return TicketService(tickets, audit), tickets, audit


def test_create_ticket_is_idempotent_and_audited():
    service, tickets, audit = make_service()

    first = service.create_ticket("10086", "MON-001", "无法点亮", "req-1", 1001)
    repeated = service.create_ticket("10086", "MON-001", "无法点亮", "req-1", 1002)

    assert first["ok"] is True
    assert first["code"] == "TICKET_CREATED"
    assert first["data"]["ticket"]["status"] == "PENDING"
    assert first["data"]["ticket_id"] == 1001
    assert repeated["code"] == "TICKET_ALREADY_CREATED"
    assert repeated["data"]["ticket_id"] == 1001
    assert len(tickets.tickets) == 1
    assert len(audit.records) == 2
    assert repeated["data"]["audit_logged"] is True


def test_create_rejects_reused_request_id_with_different_data():
    service, _, _ = make_service()
    service.create_ticket("10086", "MON-001", "无法点亮", "req-1", 1001)

    result = service.create_ticket("10086", "MON-001", "出现闪屏", "req-1", 1002)

    assert result["ok"] is False
    assert result["code"] == "IDEMPOTENCY_CONFLICT"


def test_asset_ambiguity_requires_user_choice():
    service, _, _ = make_service()

    result = service.verify_employee_asset("10086", "Dell")

    assert result["code"] == "ASSET_AMBIGUOUS"
    assert len(result["data"]["candidates"]) == 2


def test_inactive_employee_is_rejected():
    service, _, _ = make_service()

    result = service.verify_employee("99999")

    assert result["code"] == "EMPLOYEE_INACTIVE"


def test_delete_requires_preview_then_confirmation():
    service, tickets, audit = make_service()
    created = service.create_ticket("10086", "MON-001", "无法点亮", "req-create", 1001)
    ticket_id = created["data"]["ticket"]["id"]

    preview = service.delete_ticket(ticket_id, confirmed=False)
    assert preview["code"] == "DELETE_CONFIRMATION_REQUIRED"
    assert ticket_id in tickets.tickets

    deleted = service.delete_ticket(ticket_id, confirmed=True, request_id="req-delete")

    assert deleted["code"] == "TICKET_DELETED"
    assert ticket_id not in tickets.tickets
    assert audit.records[-1]["operation"] == "delete_ticket"


def test_update_validates_fields_and_status():
    service, _, _ = make_service()
    created = service.create_ticket("10086", "MON-001", "无法点亮", "req-create", 1001)
    ticket_id = created["data"]["ticket"]["id"]

    missing = service.update_ticket(ticket_id)
    invalid = service.update_ticket(ticket_id, status="UNKNOWN")
    updated = service.update_ticket(ticket_id, status="IN_PROGRESS", request_id="req-update")

    assert missing["code"] == "TOOL_INPUT_INVALID"
    assert invalid["code"] == "INVALID_TICKET_STATUS"
    assert updated["data"]["ticket"]["status"] == "IN_PROGRESS"
