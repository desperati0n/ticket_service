"""可复用的工单业务校验函数，供 CLI、流程编排和未来 AI tools 共用。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    """一次业务校验的结构化结果。"""

    ok: bool
    value: Any = None
    code: str | None = None
    message: str | None = None


def check_employee(mysql: Any, employee_no: str) -> CheckResult:
    """校验工号是否存在并返回员工对象。"""
    employee_no = (employee_no or "").strip()
    if not employee_no:
        return CheckResult(False, code="EMPLOYEE_REQUIRED", message="工号不能为空")
    employee = mysql.get_employee_by_no(employee_no)
    if not employee:
        return CheckResult(False, code="EMPLOYEE_NOT_FOUND", message="员工不存在")
    return CheckResult(True, value=employee)


def check_asset_belongs_to_employee(mysql: Any, employee_id: int, description: str) -> CheckResult:
    """校验资产已登记且属于指定员工，并返回资产对象。"""
    description = (description or "").strip()
    if not description:
        return CheckResult(False, code="ASSET_REQUIRED", message="资产描述不能为空")
    asset = mysql.verify_asset_belongs_to_employee(description, employee_id)
    if not asset:
        return CheckResult(False, code="ASSET_NOT_FOUND_OR_NOT_ASSIGNED", message="资产未登记或不属于该员工")
    return CheckResult(True, value=asset)


def check_problem_description(problem: str) -> CheckResult:
    """校验故障描述是否为空。"""
    problem = (problem or "").strip()
    if not problem:
        return CheckResult(False, code="PROBLEM_REQUIRED", message="问题描述不能为空")
    return CheckResult(True, value=problem)
