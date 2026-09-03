"""AI 工单代理使用的 Tool 参数、结果和服务端会话状态。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VerifyEmployeeInput(BaseModel):
    """员工验证 Tool 的输入。"""

    employee_no: str = Field(
        min_length=1,
        description="用户明确提供的员工工号。不得根据姓名或上下文猜测。",
    )


class VerifyAssetInput(BaseModel):
    """员工资产验证 Tool 的输入。"""

    asset_description: str = Field(
        min_length=1,
        description="用户对故障资产的名称、品牌、型号或资产编号的自然语言描述。",
    )


class CreateTicketInput(BaseModel):
    """创建工单 Tool 的输入。"""

    problem_description: str = Field(
        min_length=1,
        description="从用户原话提取的完整故障现象；不得补充用户没有表达的事实。",
    )


class AgentRequest(BaseModel):
    """自然语言 Agent 接口的请求。"""

    message: str = Field(min_length=1, description="用户当前发送的自然语言消息")
    conversation_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)


class ToolResult(BaseModel):
    """所有工单 Tool 共用的稳定返回格式。"""

    ok: bool
    code: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class VerifiedEmployee(BaseModel):
    """保存在服务器端的已验证员工信息。"""

    id: int
    employee_no: str
    name: str
    department: str


class VerifiedAsset(BaseModel):
    """保存在服务器端的已验证资产信息。"""

    id: int
    asset_code: str
    name: str
    description: str


class AgentSessionState(BaseModel):
    """一次 Agent 执行期间由服务器持有的可信业务状态。"""

    model_config = ConfigDict(validate_assignment=True)

    conversation_id: str | None = None
    employee: VerifiedEmployee | None = None
    asset: VerifiedAsset | None = None
    created_ticket_id: int | None = None
    problem_description: str | None = None
