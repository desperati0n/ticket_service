import uuid
from collections.abc import Iterator

from .repositories import MemoryMongoRepository, MemoryMySQLRepository
from .schemas import TicketRequest


class TicketFlow:
    def __init__(self, mysql: MemoryMySQLRepository, mongo: MemoryMongoRepository):
        self.mysql = mysql
        self.mongo = mongo

    def run(self, request: TicketRequest) -> Iterator[dict]:
        request_id = request.request_id or str(uuid.uuid4())
        payload = request.model_dump(exclude_none=True)
        log = self.mongo.start_log(request_id, payload)
        seq = 0

        def emit(step: str, status: str, data: dict | None = None):
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
            priority=request.priority,
        )
        yield emit("ticket_created", "success", {"ticket_id": ticket["id"], "status": ticket["status"]})
        self.mongo.finish_log(log, status="success", ticket_id=ticket["id"])
        yield emit("logged", "success", {"request_id": request_id})
        yield emit("done", "success", {"success": True, "ticket_id": ticket["id"]})

