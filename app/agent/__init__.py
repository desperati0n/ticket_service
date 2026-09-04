"""AI 工单代理的独立模块，不影响现有 CLI 和结构化流程。"""

from .agent import MAX_TOOL_CALLS, SYSTEM_PROMPT, TicketAgent, get_max_tool_calls
from .schemas import AgentRequest, AgentSessionState, TicketStatus
from .tools import build_ticket_tools

__all__ = [
    "AgentRequest",
    "AgentSessionState",
    "MAX_TOOL_CALLS",
    "get_max_tool_calls",
    "SYSTEM_PROMPT",
    "TicketStatus",
    "TicketAgent",
    "build_ticket_tools",
]
