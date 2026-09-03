from typing import Literal

from pydantic import BaseModel, Field, model_validator


Priority = Literal["normal", "urgent"]
InputType = Literal["structured", "text"]


class TicketRequest(BaseModel):
    input_type: InputType = "structured"
    employee_no: str | None = Field(default=None, min_length=1)
    asset_description: str | None = Field(default=None, min_length=1)
    problem_description: str | None = Field(default=None, min_length=1)
    priority: Priority = "normal"
    message: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_input(self) -> "TicketRequest":
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
    seq: int
    step: str
    status: Literal["started", "success", "failed"]
    data: dict = Field(default_factory=dict)

