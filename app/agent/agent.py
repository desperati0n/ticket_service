"""工单 AI 主体：提示词、Tool 调用循环和会话事件流。"""

import json
import os
import uuid
from collections.abc import Iterator
from typing import Any

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .schemas import AgentRequest, AgentSessionState
from .tools import build_ticket_tools

load_dotenv()

MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "15"))

SYSTEM_PROMPT = """你是 IT 运维工单助手。你的任务是理解用户意图，使用工具完成工单增删改查，并用简洁中文反馈结果。

工作流程：
- 创建：先 verify_employee，再 verify_employee_asset，最后 create_ticket。
- 查询单张工单：调用 get_ticket；查询列表：调用 list_tickets。
- 修改：调用 update_ticket，只传用户要求修改的字段。
- 删除：先调用 delete_ticket（confirmed=false）获取详情并请求确认，用户明确确认后再用 confirmed=true 删除。

规则：缺少必要信息就追问，不猜测；工具失败就根据返回结果处理，不声称成功；员工、资产和工单信息以工具结果为准。"""


class TicketAgent:
    """执行一次自然语言工单会话的 LangChain Agent。"""

    def __init__(self, mysql: Any, mongo: Any, model: Any | None = None):
        """注入业务仓储和可选模型；不在应用导入时强制创建模型。"""
        self.mysql = mysql
        self.mongo = mongo
        self.model = model

    def _resolve_model(self) -> Any:
        """优先使用测试或上层注入的模型，否则从 DeepSeek 配置初始化 ChatModel。"""
        if self.model is not None:
            return self.model
        model_name = os.getenv("DEEPSEEK_MODEL", "").strip()
        if not model_name:
            raise RuntimeError("MODEL_NOT_CONFIGURED: 请在 .env 中配置 DEEPSEEK_MODEL")
        return init_chat_model(
            model=model_name,
            model_provider=os.getenv("MODEL_PROVIDER", "deepseek"),
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL"),
        )

    def _history(self, conversation_id: str) -> list[dict[str, str]]:
        """读取已完成会话中的用户和助手文本；旧仓储替身没有该能力时返回空历史。"""
        getter = getattr(self.mongo, "get_agent_history", None)
        if getter is None:
            return []
        return getter(conversation_id)

    def _start_log(self, conversation_id: str, request_id: str, message: str) -> Any:
        """创建 Agent 执行日志，并兼容旧的测试仓储替身。"""
        starter = getattr(self.mongo, "start_agent_log", None)
        if starter is not None:
            return starter(conversation_id, request_id, message)
        return self.mongo.start_log(
            request_id,
            {"conversation_id": conversation_id, "message": message, "agent": True},
        )

    def _append_log(self, log: Any, event: dict[str, Any]) -> None:
        """追加一个 Agent 事件。"""
        appender = getattr(self.mongo, "append_agent_event", None)
        if appender is not None:
            appender(log, event)
        else:
            self.mongo.append_step(log, event)

    def _finish_log(
        self,
        log: Any,
        *,
        status: str,
        assistant_message: str | None = None,
        ticket_id: int | None = None,
        error: str | None = None,
    ) -> None:
        """完成 Agent 执行日志。"""
        finisher = getattr(self.mongo, "finish_agent_log", None)
        if finisher is not None:
            finisher(
                log,
                status=status,
                assistant_message=assistant_message,
                ticket_id=ticket_id,
                error=error,
            )
            return
        self.mongo.finish_log(log, status=status, ticket_id=ticket_id, error=error)

    @staticmethod
    def _content(value: Any) -> str:
        """将模型消息内容转换成可进入上下文和日志的文本。"""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _tool_result(value: Any) -> dict[str, Any]:
        """规范化 Tool 返回值，避免异常对象直接进入模型上下文。"""
        if isinstance(value, dict):
            return value
        return {
            "ok": False,
            "code": "INVALID_TOOL_RESULT",
            "message": "工具返回了无法识别的结果",
            "data": {},
            "retryable": False,
        }

    @staticmethod
    def _tool_failure(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
        """将服务器侧 Tool 异常转换成模型可以处理的结果。"""
        return {
            "ok": False,
            "code": code,
            "message": message,
            "data": {},
            "retryable": retryable,
        }

    def run(self, request: AgentRequest) -> Iterator[dict[str, Any]]:
        """运行模型与业务 Tools 的循环，并产出可直接转为 SSE 的事件。"""
        conversation_id = request.conversation_id or str(uuid.uuid4())
        request_id = request.request_id or str(uuid.uuid4())
        state = AgentSessionState(conversation_id=conversation_id)
        log = self._start_log(conversation_id, request_id, request.message)
        sequence = 0
        tool_calls_used = 0

        def emit(step: str, status: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
            """构造并持久化一个事件；调用方的 ``yield`` 再把它交给 SSE。"""
            nonlocal sequence
            sequence += 1
            event = {
                "seq": sequence,
                "step": step,
                "status": status,
                "data": data or {},
                "request_id": request_id,
                "conversation_id": conversation_id,
            }
            self._append_log(log, event)
            return event

        # 事件 1：请求已接收。yield 暂停 run，让外层立即推送首个 SSE。
        yield emit("received", "success", {"conversation_id": conversation_id})

        try:
            history = self._history(conversation_id)
            messages = [SystemMessage(content=SYSTEM_PROMPT)]
            for item in history:
                if item.get("role") == "user":
                    messages.append(HumanMessage(content=item.get("content", "")))
                elif item.get("role") == "assistant":
                    messages.append(AIMessage(content=item.get("content", "")))
            messages.append(HumanMessage(content=request.message))

            tools = build_ticket_tools(self.mysql, state)
            tool_map = {item.name: item for item in tools}
            model = self._resolve_model().bind_tools(tools)
            # 事件 2：模型和工具已准备好，告知客户端本次调用上限。
            yield emit("model_started", "success", {"tool_limit": MAX_TOOL_CALLS})

            while True:
                response = model.invoke(messages)
                messages.append(response)
                tool_calls = getattr(response, "tool_calls", None) or []

                if not tool_calls:
                    answer = self._content(getattr(response, "content", "")) or "本次请求未生成可用回复。"
                    ticket_id = state.created_ticket_id
                    self._finish_log(log, status="success", assistant_message=answer, ticket_id=ticket_id)
                    # 事件 3a：模型不再请求工具，发送最终自然语言答复。
                    yield emit("answer", "success", {"message": answer})
                    # 事件 3b：正常流程结束；下游可据此关闭 SSE 消费。
                    yield emit("done", "success", {"success": True, "ticket_id": ticket_id})
                    return

                for call in tool_calls:
                    if tool_calls_used >= MAX_TOOL_CALLS:
                        message = "本次处理已达到工具调用上限，系统已停止继续执行，请重新描述需求。"
                        self._finish_log(log, status="failed", error=message, ticket_id=state.created_ticket_id)
                        # 事件 4a：达到安全上限，停止继续执行工具。
                        yield emit(
                            "tool_limit_reached",
                            "failed",
                            {"message": message, "max_tool_calls": MAX_TOOL_CALLS},
                        )
                        # 事件 4b：失败终止信号；客户端收到后结束 SSE。
                        yield emit("done", "failed", {"success": False, "code": "TOOL_CALL_LIMIT_REACHED"})
                        return

                    tool_calls_used += 1
                    tool_name = call.get("name", "")
                    tool_args = call.get("args") or {}
                    call_id = call.get("id") or f"tool-call-{tool_calls_used}"
                    # 事件 5：工具即将执行，发送工具名、参数和累计调用次数。
                    yield emit(
                        "tool_started",
                        "success",
                        {"name": tool_name, "args": tool_args, "call_count": tool_calls_used},
                    )

                    tool = tool_map.get(tool_name)
                    if tool is None:
                        result = self._tool_failure(
                            "UNKNOWN_TOOL",
                            f"未注册的工具：{tool_name}",
                            retryable=False,
                        )
                    else:
                        try:
                            result = self._tool_result(tool.invoke(tool_args))
                        except ValueError:
                            result = self._tool_failure(
                                "TOOL_INPUT_INVALID",
                                "工具参数无效，请根据参数说明重新调用。",
                                retryable=True,
                            )
                        except Exception:
                            result = self._tool_failure(
                                "TOOL_EXECUTION_FAILED",
                                "工具执行失败，请稍后重试或向用户说明暂时无法完成操作。",
                                retryable=False,
                            )

                    messages.append(
                        ToolMessage(
                            content=json.dumps(result, ensure_ascii=False, default=str),
                            tool_call_id=call_id,
                        )
                    )
                    # 事件 6：工具已执行，发送统一结果；随后回到模型循环。
                    yield emit(
                        "tool_finished",
                        "success" if result.get("ok") else "failed",
                        {
                            "name": tool_name,
                            "code": result.get("code"),
                            "message": result.get("message"),
                            "data": result.get("data", {}),
                            "call_count": tool_calls_used,
                        },
                    )
        except Exception as exc:
            message = f"Agent 执行失败：{exc}"
            self._finish_log(log, status="failed", error=message, ticket_id=state.created_ticket_id)
            # 事件 7a：捕获未处理异常，将服务端错误转成可展示的事件。
            yield emit("error", "failed", {"code": "AGENT_EXECUTION_FAILED", "message": message})
            # 事件 7b：异常终止信号；客户端收到后结束 SSE。
            yield emit("done", "failed", {"success": False, "code": "AGENT_EXECUTION_FAILED"})
