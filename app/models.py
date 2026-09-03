"""业务数据模型。"""

from dataclasses import dataclass


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
    status: str = "in_use"
