"""工单 Agent 主体、调用上限、日志和 FastAPI SSE 测试。"""

from langchain_core.messages import AIMessage

from app.agent import AgentRequest, SYSTEM_PROMPT, TicketAgent
from app.main import app
from fastapi.testclient import TestClient


class FakeAgentMongo:
    """只实现 Agent 所需接口的 MongoDB 测试替身。"""

    def __init__(self):
        self.logs = []

    def start_agent_log(self, conversation_id, request_id, message):
        log = {
            "conversation_id": conversation_id,
            "request_id": request_id,
            "input": {"message": message},
            "events": [],
            "status": "started",
        }
        self.logs.append(log)
        return log

    def append_agent_event(self, log, event):
        log["events"].append(event)

    def finish_agent_log(self, log, *, status, assistant_message=None, ticket_id=None, error=None):
        log.update(
            {
                "status": status,
                "assistant_message": assistant_message,
                "ticket_id": ticket_id,
                "error": error,
            }
        )

    def get_agent_history(self, conversation_id, limit=20):
        return []


class ScriptedModel:
    """按预置消息返回结果，模拟支持 bind_tools 的 ChatModel。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        return self.responses.pop(0)


def tool_message(name, args, call_id):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def successful_model():
    return ScriptedModel(
        [
            tool_message("verify_employee", {"employee_no": "10086"}, "call-1"),
            tool_message("verify_employee_asset", {"asset_description": "Dell"}, "call-2"),
            tool_message("create_ticket", {"problem_description": "无法点亮，急用"}, "call-3"),
            AIMessage(content="报修已提交，工单状态为待处理。"),
        ]
    )


def test_system_prompt_clearly_describes_agent_job_and_flow():
    """系统提示词应简短但覆盖任务、CRUD 流程和基本约束。"""
    assert len(SYSTEM_PROMPT) < 600
    assert "理解用户意图" in SYSTEM_PROMPT
    assert "verify_employee" in SYSTEM_PROMPT
    assert "verify_employee_asset" in SYSTEM_PROMPT
    assert "create_ticket" in SYSTEM_PROMPT
    assert "get_ticket" in SYSTEM_PROMPT
    assert "list_tickets" in SYSTEM_PROMPT
    assert "update_ticket" in SYSTEM_PROMPT
    assert "delete_ticket" in SYSTEM_PROMPT
    assert "不猜测" in SYSTEM_PROMPT


def test_agent_runs_business_flow_and_persists_events(repositories):
    """Agent 应按员工、资产、工单顺序调用 Tool，并记录完整事件。"""
    mysql, _ = repositories
    mongo = FakeAgentMongo()
    model = successful_model()
    agent = TicketAgent(mysql, mongo, model=model)

    events = list(
        agent.run(
            AgentRequest(
                conversation_id="conversation-1",
                request_id="request-1",
                message="我的 Dell 显示器坏了，工号 10086，急用",
            )
        )
    )

    tool_names = [event["data"]["name"] for event in events if event["step"] == "tool_started"]
    assert tool_names == ["verify_employee", "verify_employee_asset", "create_ticket"]
    assert events[-1]["step"] == "done"
    assert events[-1]["data"] == {"success": True, "ticket_id": mysql.tickets[0]["id"]}
    assert mongo.logs[0]["status"] == "success"
    assert mongo.logs[0]["assistant_message"] == "报修已提交，工单状态为待处理。"
    assert len(mongo.logs[0]["events"]) == len(events)
    assert model.bound_tools is not None


def test_agent_stops_after_fifteen_tool_calls(repositories):
    """无论模型是否继续请求，Tool 总调用次数都不能超过 15 次。"""
    mysql, _ = repositories
    mongo = FakeAgentMongo()
    model = ScriptedModel(
        [
            tool_message("verify_employee", {"employee_no": "10086"}, f"call-{index}")
            for index in range(16)
        ]
    )
    agent = TicketAgent(mysql, mongo, model=model)

    events = list(agent.run(AgentRequest(message="请处理我的报修")))

    started = [event for event in events if event["step"] == "tool_started"]
    assert len(started) == 15
    assert any(event["step"] == "tool_limit_reached" for event in events)
    assert events[-1]["data"]["code"] == "TOOL_CALL_LIMIT_REACHED"
    assert mongo.logs[0]["status"] == "failed"
    assert mysql.tickets == []


def test_agent_returns_configuration_error_without_model_settings(repositories, monkeypatch):
    """未配置模型时应通过 SSE 事件返回可理解的错误，而不是抛出异常。"""
    mysql, _ = repositories
    mongo = FakeAgentMongo()
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    events = list(TicketAgent(mysql, mongo).run(AgentRequest(message="显示器坏了")))

    assert events[-2]["step"] == "error"
    assert events[-2]["data"]["code"] == "AGENT_EXECUTION_FAILED"
    assert "MODEL_NOT_CONFIGURED" in events[-2]["data"]["message"]
    assert events[-1]["step"] == "done"
    assert mongo.logs[0]["status"] == "failed"


def test_invalid_tool_arguments_are_returned_to_model(repositories):
    """Tool 参数校验失败时，模型应收到结构化错误而不是直接中断。"""
    mysql, _ = repositories
    mongo = FakeAgentMongo()
    model = ScriptedModel(
        [
            tool_message("verify_employee", {"employee_no": ""}, "invalid-call"),
            AIMessage(content="请提供有效的员工工号。"),
        ]
    )

    events = list(TicketAgent(mysql, mongo, model=model).run(AgentRequest(message="帮我报修")))

    failed = [event for event in events if event["step"] == "tool_finished"][-1]
    assert failed["status"] == "failed"
    assert failed["data"]["code"] == "TOOL_INPUT_INVALID"
    assert events[-2]["data"]["message"] == "请提供有效的员工工号。"


def test_chat_stream_exposes_agent_events(repositories, monkeypatch):
    """FastAPI 自然语言入口应按 SSE 返回 Agent 事件。"""
    mysql, _ = repositories
    mongo = FakeAgentMongo()
    import app.main as app_main

    monkeypatch.setattr(app_main, "ticket_agent", TicketAgent(mysql, mongo, model=successful_model()))
    response = TestClient(app).post(
        "/chat/stream",
        json={"message": "我的 Dell 显示器坏了，工号 10086，急用"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: tool_started" in response.text
    assert "event: answer" in response.text
    assert "event: done" in response.text
