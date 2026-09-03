"""本模块提供测试和本地演示使用的内存仓储。"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Employee:
    """员工模型描述一名公司员工及其当前状态。"""
    id: int
    employee_no: str
    name: str
    department: str
    status: str = "active"


@dataclass(frozen=True)
class Asset:
    """资产模型描述一项可分配给员工的公司资产。"""
    id: int
    asset_code: str
    name: str
    assigned_employee_id: int | None = None
    status: str = "in_use"


class MemoryMySQLRepository:
    """内存业务仓储在无外部服务时模拟 MySQL 操作。"""

    def __init__(self, id_generator):
        """初始化固定的员工、资产和工单集合。"""
        self._id = id_generator
        self.employees = {"10086": Employee(10086, "10086", "张三", "研发部")}
        self.assets = [Asset(self._id.next_id(), "A-001", "Dell 显示器", 10086)]
        self.tickets: list[dict] = []

    def get_employee_by_no(self, employee_no: str) -> Employee | None:
        """从内存索引中按工号返回员工。"""
        return self.employees.get(str(employee_no))

    def find_asset(self, description: str, employee_id: int) -> Asset | None:
        """返回分配给员工且与描述匹配的内存资产。"""
        text = description.lower()
        for asset in self.assets:
            if asset.assigned_employee_id in (None, employee_id) and (
                text in asset.name.lower() or asset.name.lower() in text
            ):
                return asset
        return None

    def create_ticket(self, *, employee: Employee, asset: Asset | None, issue: str) -> dict:
        """在内存中创建一张待处理工单。"""
        ticket = {
            "id": self._id.next_id(),
            "employee_id": employee.id,
            "asset_id": asset.id if asset else None,
            "issue": issue,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.tickets.append(ticket)
        return ticket

    def get_ticket(self, ticket_id: int) -> dict | None:
        """按 ID 返回一张内存工单。"""
        return next((ticket for ticket in self.tickets if ticket["id"] == ticket_id), None)

    def list_tickets(self, employee_no: str | None = None) -> list[dict]:
        """返回全部内存工单或某名员工的工单。"""
        if employee_no is None:
            return list(reversed(self.tickets))
        employee = self.get_employee_by_no(employee_no)
        if not employee:
            return []
        return list(reversed([ticket for ticket in self.tickets if ticket["employee_id"] == employee.id]))


class MemoryMongoRepository:
    """内存日志仓储为测试模拟 MongoDB 请求记录。"""

    def __init__(self):
        """初始化空的内存日志集合。"""
        self.logs: list[dict] = []

    def start_log(self, request_id: str, payload: dict) -> dict:
        """保存并返回一条新的内存请求日志。"""
        log = {"request_id": request_id, "input": payload, "steps": [], "status": "started"}
        self.logs.append(log)
        return log

    def append_step(self, log: dict, step: dict) -> None:
        """向内存请求日志追加一个流程步骤。"""
        log["steps"].append(step)

    def finish_log(self, log: dict, *, status: str, ticket_id: int | None = None, error: str | None = None) -> None:
        """将内存请求日志标记为完成或失败。"""
        log["status"] = status
        log["ticket_id"] = ticket_id
        if error:
            log["error"] = error
