"""本模块负责组装 FastAPI、仓储和工单业务流程。"""

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from .agent import AgentRequest, TicketAgent
from .ids import Snowflake
from .real_repositories import MongoRepository, MySQLRepository
from .schemas import TicketRequest
from .service import TicketFlow

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
id_generator = Snowflake()
mysql_repository = MySQLRepository(id_generator)
mongo_repository = MongoRepository()
flow = TicketFlow(mysql_repository, mongo_repository)
ticket_agent = TicketAgent(mysql_repository, mongo_repository)

app = FastAPI(title=os.getenv("APP_NAME", "IT运维助手 Demo"))


def sse_stream(request: TicketRequest):
    """将业务流程事件序列化为 SSE 数据帧。"""
    for event in flow.run(request):
        yield f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
def health() -> dict:
    """返回服务健康状态和运行环境。"""
    return {"status": "ok", "environment": os.getenv("APP_ENV", "development")}


@app.post("/ticket/stream")
def create_ticket_stream(request: TicketRequest):
    """创建工单并流式返回每个业务步骤。"""
    return StreamingResponse(sse_stream(request), media_type="text/event-stream")


def agent_sse_stream(request: AgentRequest):
    """将自然语言 Agent 事件序列化为 SSE 数据帧。"""
    for event in ticket_agent.run(request):
        yield f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
def chat_stream(request: AgentRequest):
    """接收自然语言报修消息，并流式返回模型和 Tool 的处理过程。"""
    return StreamingResponse(
        agent_sse_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
