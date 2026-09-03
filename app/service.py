"""本模块编排请求记录、员工查询、资产查询和工单创建流程。"""

import uuid
from collections.abc import Iterator
from typing import Any

from .schemas import TicketRequest


class TicketFlow:
    """工单流程执行无 AI 的结构化报修业务。"""

    def __init__(self, mysql: Any, mongo: Any):
        """使用业务仓储和日志仓储初始化流程。"""
        self.mysql = mysql
        self.mongo = mongo

    def run(self, request: TicketRequest) -> Iterator[dict]:
        """创建工单并依次产出处理事件。"""
        request_id = request.request_id or str(uuid.uuid4())
        payload = request.model_dump(exclude_none=True)
        log = self.mongo.start_log(request_id, payload)
        seq = 0

        def emit(step: str, status: str, data: dict | None = None):
            """创建、保存并返回一个流程事件。"""
            nonlocal seq
            seq += 1
            event = {"seq": seq, "step": step, "status": status, "data": data or {}, "request_id": request_id}
            self.mongo.append_step(log, event)
            return event

        yield emit("received", "success", {"input_type": request.input_type})
        if request.input_type == "text":
            error = "text input is reserved for the future AI adapter"
            yield emit("error", "failed", {"code": "AI_NOT_ENABLED", "message": error})
            self.mongo.finish_log(log, status="failed", error=error)
            return

        employee = self.mysql.get_employee_by_no(request.employee_no or "")
        if not employee:
            error = "employee not found"
            yield emit("employee_lookup", "failed", {"code": "EMPLOYEE_NOT_FOUND", "message": error})
            self.mongo.finish_log(log, status="failed", error=error)
            return
        yield emit("employee_lookup", "success", {"employee_no": employee.employee_no, "name": employee.name})

        asset = self.mysql.find_asset(request.asset_description or "", employee.id)
        yield emit("asset_lookup", "success", {"asset_id": asset.id if asset else None, "matched": bool(asset)})

        ticket = self.mysql.create_ticket(
            employee=employee,
            asset=asset,
            issue=request.problem_description or "",
        )
        yield emit("ticket_created", "success", {"ticket_id": ticket["id"], "status": ticket["status"]})
        self.mongo.finish_log(log, status="success", ticket_id=ticket["id"])
        yield emit("logged", "success", {"request_id": request_id})
        yield emit("done", "success", {"success": True, "ticket_id": ticket["id"]})

