"""Deterministic ticket use cases exposed by the MCP tools."""

from typing import Any, Protocol
import uuid

from .models import Asset, Employee


ALLOWED_STATUSES = {"PENDING", "IN_PROGRESS", "RESOLVED", "CANCELLED"}


class TicketRepository(Protocol):
    def get_employee_by_no(self, employee_no: str) -> Employee | None: ...
    def find_employee_assets(self, employee_id: int, query: str) -> list[Asset]: ...
    def create_ticket(
        self, *, ticket_id: int, employee_no: str, asset_id: int, issue: str, request_id: str
    ) -> tuple[dict[str, Any], bool]: ...
    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None: ...
    def list_tickets(self, employee_no: str | None, limit: int) -> list[dict[str, Any]]: ...
    def update_ticket(
        self, ticket_id: int, *, issue: str | None, status: str | None
    ) -> dict[str, Any] | None: ...
    def delete_ticket(self, ticket_id: int) -> bool: ...


class AuditRepository(Protocol):
    def record(
        self, *, operation: str, request_id: str, payload: dict[str, Any], result: dict[str, Any]
    ) -> bool: ...


def _result(
    ok: bool,
    code: str,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "code": code,
        "message": message,
        "data": data or {},
        "retryable": retryable,
    }


def _clean(value: str, field: str, *, max_length: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    if len(cleaned) > max_length:
        raise ValueError(f"{field} is too long")
    return cleaned


class TicketService:
    """Keep all business invariants independent of the calling Agent."""

    def __init__(self, tickets: TicketRepository, audit: AuditRepository | None = None):
        self.tickets = tickets
        self.audit = audit

    def verify_employee(self, employee_no: str) -> dict[str, Any]:
        try:
            employee_no = _clean(employee_no, "employee_no", max_length=64)
        except ValueError as exc:
            return _result(False, "TOOL_INPUT_INVALID", str(exc), retryable=True)
        employee = self.tickets.get_employee_by_no(employee_no)
        if employee is None:
            return _result(False, "EMPLOYEE_NOT_FOUND", "未找到对应员工", retryable=True)
        if employee.status != "active":
            return _result(False, "EMPLOYEE_INACTIVE", "该员工当前不可创建工单")
        return _result(
            True,
            "EMPLOYEE_VERIFIED",
            "员工身份已确认",
            data={
                "employee_no": employee.employee_no,
                "name": employee.name,
                "department": employee.department,
            },
        )

    def verify_employee_asset(self, employee_no: str, asset_description: str) -> dict[str, Any]:
        employee_result = self.verify_employee(employee_no)
        if not employee_result["ok"]:
            return employee_result
        try:
            description = _clean(asset_description, "asset_description", max_length=256)
        except ValueError as exc:
            return _result(False, "TOOL_INPUT_INVALID", str(exc), retryable=True)
        employee = self.tickets.get_employee_by_no(employee_no.strip())
        assert employee is not None
        assets = self.tickets.find_employee_assets(employee.id, description)
        if not assets:
            return _result(
                False,
                "ASSET_NOT_FOUND",
                "未找到该员工名下匹配的资产，请补充名称、型号或资产编号",
                retryable=True,
            )
        if len(assets) > 1:
            return _result(
                False,
                "ASSET_AMBIGUOUS",
                "匹配到多项资产，请让用户明确选择资产编号",
                data={"candidates": [self._asset_data(asset) for asset in assets]},
                retryable=True,
            )
        return _result(
            True,
            "ASSET_VERIFIED",
            "员工资产已确认",
            data=self._asset_data(assets[0]),
        )

    @staticmethod
    def _asset_data(asset: Asset) -> dict[str, Any]:
        return {"asset_id": asset.id, "asset_code": asset.asset_code, "name": asset.name}

    def create_ticket(
        self,
        employee_no: str,
        asset_description: str,
        problem_description: str,
        request_id: str,
        ticket_id: int,
    ) -> dict[str, Any]:
        if ticket_id <= 0:
            return _result(False, "TOOL_INPUT_INVALID", "ticket_id 必须是正整数")
        try:
            employee_no = _clean(employee_no, "employee_no", max_length=64)
            asset_description = _clean(asset_description, "asset_description", max_length=256)
            problem_description = _clean(
                problem_description, "problem_description", max_length=4000
            )
            request_id = _clean(request_id, "request_id", max_length=64)
        except ValueError as exc:
            return _result(False, "TOOL_INPUT_INVALID", str(exc), retryable=True)

        asset_result = self.verify_employee_asset(employee_no, asset_description)
        if not asset_result["ok"]:
            return asset_result
        try:
            ticket, created = self.tickets.create_ticket(
                ticket_id=ticket_id,
                employee_no=employee_no,
                asset_id=asset_result["data"]["asset_id"],
                issue=problem_description,
                request_id=request_id,
            )
        except LookupError:
            return _result(
                False,
                "VERIFICATION_EXPIRED",
                "员工或资产归属已经变化，请重新确认",
                retryable=True,
            )
        except ValueError:
            return _result(
                False,
                "IDEMPOTENCY_CONFLICT",
                "该 request_id 已用于另一组工单数据，请勿重复使用",
            )

        result = _result(
            True,
            "TICKET_CREATED" if created else "TICKET_ALREADY_CREATED",
            "维修工单已创建" if created else "相同请求的工单已经存在",
            data={
                "ticket_id": ticket["id"],
                "status": ticket["status"],
                "ticket": ticket,
                "created": created,
            },
        )
        self._audit(
            result,
            operation="create_ticket",
            request_id=request_id,
            payload={
                "employee_no": employee_no,
                "asset_description": asset_description,
                "problem_description": problem_description,
            },
        )
        return result

    def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        if ticket_id <= 0:
            return _result(False, "TOOL_INPUT_INVALID", "ticket_id 必须是正整数", retryable=True)
        ticket = self.tickets.get_ticket(ticket_id)
        if ticket is None:
            return _result(False, "TICKET_NOT_FOUND", "未找到对应工单", retryable=True)
        return _result(True, "TICKET_FOUND", "已找到工单", data={"ticket": ticket})

    def list_tickets(self, employee_no: str | None = None, limit: int = 50) -> dict[str, Any]:
        if employee_no is not None:
            try:
                employee_no = _clean(employee_no, "employee_no", max_length=64)
            except ValueError as exc:
                return _result(False, "TOOL_INPUT_INVALID", str(exc), retryable=True)
        if limit < 1 or limit > 100:
            return _result(False, "TOOL_INPUT_INVALID", "limit 必须在 1 到 100 之间", retryable=True)
        tickets = self.tickets.list_tickets(employee_no, limit)
        return _result(
            True,
            "TICKETS_LISTED",
            "工单列表查询完成",
            data={"count": len(tickets), "tickets": tickets},
        )

    def update_ticket(
        self,
        ticket_id: int,
        issue: str | None = None,
        status: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if ticket_id <= 0:
            return _result(False, "TOOL_INPUT_INVALID", "ticket_id 必须是正整数", retryable=True)
        if issue is None and status is None:
            return _result(
                False,
                "TOOL_INPUT_INVALID",
                "必须提供 issue 或 status 中的至少一个字段",
                retryable=True,
            )
        try:
            issue = _clean(issue, "issue", max_length=4000) if issue is not None else None
            request_id = (
                _clean(request_id, "request_id", max_length=64)
                if request_id is not None
                else str(uuid.uuid4())
            )
        except ValueError as exc:
            return _result(False, "TOOL_INPUT_INVALID", str(exc), retryable=True)
        if status is not None and status not in ALLOWED_STATUSES:
            return _result(False, "INVALID_TICKET_STATUS", "工单状态不在允许范围内", retryable=True)
        ticket = self.tickets.update_ticket(ticket_id, issue=issue, status=status)
        if ticket is None:
            return _result(False, "TICKET_NOT_FOUND", "未找到对应工单", retryable=True)
        result = _result(True, "TICKET_UPDATED", "工单已更新", data={"ticket": ticket})
        self._audit(
            result,
            operation="update_ticket",
            request_id=request_id,
            payload={"ticket_id": ticket_id, "issue": issue, "status": status},
        )
        return result

    def delete_ticket(
        self,
        ticket_id: int,
        confirmed: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_ticket(ticket_id)
        if not current["ok"]:
            return current
        if not confirmed:
            return _result(
                False,
                "DELETE_CONFIRMATION_REQUIRED",
                "删除工单属于不可逆操作，需要用户明确确认",
                data={"ticket": current["data"]["ticket"]},
                retryable=True,
            )
        request_id = request_id.strip() if request_id and request_id.strip() else str(uuid.uuid4())
        deleted = self.tickets.delete_ticket(ticket_id)
        if not deleted:
            return _result(False, "TICKET_DELETE_FAILED", "工单删除失败，请重新查询后再试")
        result = _result(
            True,
            "TICKET_DELETED",
            "工单已删除",
            data={"ticket_id": ticket_id},
        )
        self._audit(
            result,
            operation="delete_ticket",
            request_id=request_id,
            payload={"ticket_id": ticket_id},
        )
        return result

    def _audit(
        self,
        result: dict[str, Any],
        *,
        operation: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> None:
        audit_logged = False
        if self.audit is not None:
            audit_logged = self.audit.record(
                operation=operation,
                request_id=request_id,
                payload=payload,
                result=result,
            )
        result["data"]["audit_logged"] = audit_logged
