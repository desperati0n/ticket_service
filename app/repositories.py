from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Employee:
    id: int
    employee_no: str
    name: str
    department: str
    status: str = "active"


@dataclass(frozen=True)
class Asset:
    id: int
    asset_code: str
    name: str
    assigned_employee_id: int | None = None
    status: str = "in_use"


class MemoryMySQLRepository:
    """Deterministic repository used by the runnable demo and tests."""

    def __init__(self, id_generator):
        self._id = id_generator
        self.employees = {"10086": Employee(10086, "10086", "张三", "研发部")}
        self.assets = [Asset(self._id.next_id(), "A-001", "Dell 显示器", 10086)]
        self.tickets: list[dict] = []

    def get_employee_by_no(self, employee_no: str) -> Employee | None:
        return self.employees.get(str(employee_no))

    def find_asset(self, description: str, employee_id: int) -> Asset | None:
        text = description.lower()
        for asset in self.assets:
            if asset.assigned_employee_id in (None, employee_id) and (
                text in asset.name.lower() or asset.name.lower() in text
            ):
                return asset
        return None

    def create_ticket(self, *, employee: Employee, asset: Asset | None, issue: str, priority: str) -> dict:
        ticket = {
            "id": self._id.next_id(),
            "employee_id": employee.id,
            "asset_id": asset.id if asset else None,
            "issue": issue,
            "priority": priority,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.tickets.append(ticket)
        return ticket

    def get_ticket(self, ticket_id: int) -> dict | None:
        return next((ticket for ticket in self.tickets if ticket["id"] == ticket_id), None)


class MemoryMongoRepository:
    def __init__(self):
        self.logs: list[dict] = []

    def start_log(self, request_id: str, payload: dict) -> dict:
        log = {"request_id": request_id, "input": payload, "steps": [], "status": "started"}
        self.logs.append(log)
        return log

    def append_step(self, log: dict, step: dict) -> None:
        log["steps"].append(step)

    def finish_log(self, log: dict, *, status: str, ticket_id: int | None = None, error: str | None = None) -> None:
        log["status"] = status
        log["ticket_id"] = ticket_id
        if error:
            log["error"] = error
