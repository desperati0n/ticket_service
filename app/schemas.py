"""本模块定义 API 请求和 SSE 事件的数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


InputType = Literal["structured", "text"]


class TicketRequest(BaseModel):
    """工单请求包含创建维修工单所需的输入字段。"""
    input_type: InputType = "structured"
    employee_no: str | None = Field(default=None, min_length=1)
    asset_description: str | None = Field(default=None, min_length=1)
    problem_description: str | None = Field(default=None, min_length=1)
    message: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_input(self) -> "TicketRequest":
        """根据输入类型校验对应的必填字段。"""
        if self.input_type == "structured":
            missing = [
                name
                for name in ("employee_no", "asset_description", "problem_description")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(f"structured input missing: {', '.join(missing)}")
        elif not self.message:
            raise ValueError("text input requires message")
        return self


class SSEEvent(BaseModel):
    """SSE 事件描述工单处理中的一个可观察步骤。"""
    seq: int
    step: str
    status: Literal["started", "success", "failed"]
    data: dict = Field(default_factory=dict)

