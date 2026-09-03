"""独立的 LangChain 工单 Tools，复用现有业务校验但不修改现有流程。"""

from typing import Any

from langchain_core.tools import BaseTool, tool

from ..operations import check_asset_belongs_to_employee, check_employee, check_problem_description
from .schemas import (
    AgentSessionState,
    CreateTicketInput,
    DeleteTicketInput,
    ListTicketsInput,
    TicketIdInput,
    ToolResult,
    UpdateTicketInput,
    VerifiedAsset,
    VerifiedEmployee,
    VerifyAssetInput,
    VerifyEmployeeInput,
)


def _result(
    ok: bool,
    code: str,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """生成适合返回给模型的统一 Tool 结果。"""
    return ToolResult(
        ok=ok,
        code=code,
        message=message,
        data=data or {},
        retryable=retryable,
    ).model_dump(mode="json")


def build_ticket_tools(mysql: Any, state: AgentSessionState) -> list[BaseTool]:
    """为一次 Agent 会话构建绑定仓储和可信状态的工单 Tools。"""

    @tool("verify_employee", args_schema=VerifyEmployeeInput)
    def verify_employee(employee_no: str) -> dict[str, Any]:
        """根据用户明确提供的工号验证员工。创建工单前必须先调用；失败后应向用户重新询问工号，不得继续验证资产。"""
        checked = check_employee(mysql, employee_no)
        if not checked.ok:
            state.employee = None
            state.asset = None
            return _result(
                False,
                checked.code or "EMPLOYEE_VERIFICATION_FAILED",
                checked.message or "员工验证失败",
                retryable=True,
            )

        employee = checked.value
        if state.employee is None or state.employee.id != employee.id:
            state.asset = None
        state.employee = VerifiedEmployee(
            id=employee.id,
            employee_no=employee.employee_no,
            name=employee.name,
            department=employee.department,
        )
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

    @tool("verify_employee_asset", args_schema=VerifyAssetInput)
    def verify_employee_asset(asset_description: str) -> dict[str, Any]:
        """验证自然语言描述的资产属于当前已验证员工。只能在员工验证成功后调用；失败时应请用户补充资产名称、型号或编号。"""
        if state.employee is None:
            return _result(
                False,
                "EMPLOYEE_CONTEXT_REQUIRED",
                "请先验证员工工号",
                retryable=True,
            )

        checked = check_asset_belongs_to_employee(mysql, state.employee.id, asset_description)
        if not checked.ok:
            state.asset = None
            return _result(
                False,
                checked.code or "ASSET_VERIFICATION_FAILED",
                checked.message or "资产验证失败",
                retryable=True,
            )

        asset = checked.value
        state.asset = VerifiedAsset(
            id=asset.id,
            asset_code=asset.asset_code,
            name=asset.name,
            description=asset_description.strip(),
        )
        return _result(
            True,
            "ASSET_VERIFIED",
            "员工资产已确认",
            data={"asset_code": asset.asset_code, "name": asset.name},
        )

    @tool("create_ticket", args_schema=CreateTicketInput)
    def create_ticket(problem_description: str) -> dict[str, Any]:
        """为当前已验证的员工和资产创建待处理工单。只能在两项验证均成功且故障描述明确时调用；不得猜测员工、资产或故障事实。"""
        if state.employee is None:
            return _result(False, "EMPLOYEE_CONTEXT_REQUIRED", "请先验证员工工号", retryable=True)
        if state.asset is None:
            return _result(False, "ASSET_CONTEXT_REQUIRED", "请先验证员工名下的故障资产", retryable=True)
        if state.created_ticket_id is not None:
            return _result(
                True,
                "TICKET_ALREADY_CREATED",
                "本次会话已经创建过工单",
                data={"ticket_id": state.created_ticket_id, "status": "PENDING"},
            )

        problem_check = check_problem_description(problem_description)
        if not problem_check.ok:
            return _result(
                False,
                problem_check.code or "PROBLEM_VERIFICATION_FAILED",
                problem_check.message or "故障描述验证失败",
                retryable=True,
            )

        employee_check = check_employee(mysql, state.employee.employee_no)
        if not employee_check.ok or employee_check.value.id != state.employee.id:
            state.employee = None
            state.asset = None
            return _result(False, "EMPLOYEE_CONTEXT_EXPIRED", "员工信息已变化，请重新验证工号", retryable=True)

        asset_check = check_asset_belongs_to_employee(
            mysql,
            employee_check.value.id,
            state.asset.description,
        )
        if not asset_check.ok or asset_check.value.id != state.asset.id:
            state.asset = None
            return _result(False, "ASSET_CONTEXT_EXPIRED", "资产归属已变化，请重新确认资产", retryable=True)

        ticket = mysql.create_ticket(
            employee=employee_check.value,
            asset=asset_check.value,
            issue=problem_check.value,
        )
        state.created_ticket_id = ticket["id"]
        state.problem_description = problem_check.value
        return _result(
            True,
            "TICKET_CREATED",
            "维修工单已创建",
            data={"ticket_id": ticket["id"], "status": ticket["status"]},
        )

    @tool("get_ticket", args_schema=TicketIdInput)
    def get_ticket(ticket_id: int) -> dict[str, Any]:
        """根据工单 ID 查询工单详情。找不到时返回错误结果，不要编造工单信息。"""
        ticket = mysql.get_ticket(ticket_id)
        if ticket is None:
            return _result(False, "TICKET_NOT_FOUND", "未找到对应工单", retryable=True)
        return _result(True, "TICKET_FOUND", "已找到工单", data={"ticket": ticket})

    @tool("list_tickets", args_schema=ListTicketsInput)
    def list_tickets(employee_no: str | None = None) -> dict[str, Any]:
        """查询工单列表。提供员工工号时只查询该员工的历史工单，不提供时查询全部工单。"""
        tickets = mysql.list_tickets(employee_no.strip() if employee_no else None)
        return _result(
            True,
            "TICKETS_LISTED",
            "工单列表查询完成",
            data={"count": len(tickets), "tickets": tickets},
        )

    @tool("update_ticket", args_schema=UpdateTicketInput)
    def update_ticket(ticket_id: int, issue: str | None = None, status: str | None = None) -> dict[str, Any]:
        """修改工单的问题描述或状态。必须提供至少一个修改字段，状态只能使用允许的枚举值。"""
        current = mysql.get_ticket(ticket_id)
        if current is None:
            return _result(False, "TICKET_NOT_FOUND", "未找到对应工单", retryable=True)
        updated = mysql.update_ticket(ticket_id, issue=issue, status=status)
        if updated is None:
            return _result(False, "TICKET_UPDATE_FAILED", "工单更新失败，请稍后重试")
        return _result(True, "TICKET_UPDATED", "工单已更新", data={"ticket": updated})

    @tool("delete_ticket", args_schema=DeleteTicketInput)
    def delete_ticket(ticket_id: int, confirmed: bool = False) -> dict[str, Any]:
        """删除工单。第一次调用必须保持 confirmed=false 以取得待删除详情；只有用户明确确认后才能传 true 执行删除。"""
        ticket = mysql.get_ticket(ticket_id)
        if ticket is None:
            return _result(False, "TICKET_NOT_FOUND", "未找到对应工单", retryable=True)
        if not confirmed:
            return _result(
                False,
                "DELETE_CONFIRMATION_REQUIRED",
                "删除工单属于不可逆操作，需要用户明确确认",
                data={"ticket": ticket},
                retryable=True,
            )
        if not mysql.delete_ticket(ticket_id):
            return _result(False, "TICKET_DELETE_FAILED", "工单删除失败，请稍后重试")
        return _result(True, "TICKET_DELETED", "工单已删除", data={"ticket_id": ticket_id})

    return [
        verify_employee,
        verify_employee_asset,
        create_ticket,
        get_ticket,
        list_tickets,
        update_ticket,
        delete_ticket,
    ]
