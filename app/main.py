"""本模块负责组装 FastAPI、仓储和工单业务流程。"""

import json
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from pydantic import Field

from .agent import AgentRequest, TicketAgent
from .ids import Snowflake
from .real_repositories import MongoRepository, MySQLRepository
from .queue import TaskQueue
from .schemas import BatchQueuedResponse, QueuedTaskResponse, TaskStatusResponse, TicketRequest
from .service import TicketFlow

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
id_generator = Snowflake(worker_id=int(os.getenv("SNOWFLAKE_API_WORKER_ID", "1")))
mysql_repository = MySQLRepository(id_generator)
mongo_repository = MongoRepository()
flow = TicketFlow(mysql_repository, mongo_repository)
ticket_agent = TicketAgent(mysql_repository, mongo_repository)
task_queue = TaskQueue()

app = FastAPI(
    title=os.getenv("OPENAPI_TITLE", "IT 运维助手 Demo API"),
    description="内部 IT 运维助手的同步、流式和后台队列接口。",
    version="0.1.0",
)

#无AI业务逻辑
def sse_stream(request: TicketRequest):
    """将业务流程事件序列化为 SSE 数据帧。"""
    for event in flow.run(request):
        yield f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

#有AI业务逻辑
def agent_sse_stream(request: AgentRequest):
    """将自然语言 Agent 事件序列化为 SSE 数据帧。"""
    for event in ticket_agent.run(request):
        yield f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"



@app.get("/health")
def health() -> dict:
    """返回服务健康状态和运行环境。"""
    return {"status": "ok", "environment": os.getenv("APP_ENV", "development")}


@app.post("/ticket/stream")
def create_ticket_stream(request: TicketRequest):
    """创建工单并流式返回每个业务步骤。"""
    return StreamingResponse(sse_stream(request), media_type="text/event-stream")

@app.post("/chat/stream")
def chat_stream(request: AgentRequest):
    """接收自然语言报修消息，并流式返回模型和 Tool 的处理过程。"""
    return StreamingResponse(
        agent_sse_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post(
    "/ticket/task",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=QueuedTaskResponse | BatchQueuedResponse,
    responses={503: {"description": "任务队列暂时不可用"}},
)
def enqueue_ticket_task(
    request: AgentRequest | Annotated[list[AgentRequest], Field(min_length=1, max_length=100)],
) -> QueuedTaskResponse | BatchQueuedResponse:
    """接收单条或批量自然语言报修并立即投递到后台 Worker。"""
    if isinstance(request, list):
        tasks = [_enqueue_one_ticket_task(item) for item in request]
        return BatchQueuedResponse(status="queued", total=len(tasks), tasks=tasks)
    return _enqueue_one_ticket_task(request)


def _enqueue_one_ticket_task(request: AgentRequest) -> QueuedTaskResponse:
    """生成雪花任务 ID，记录任务并写入 Redis Stream。"""
    task_id = request.request_id or str(id_generator.next_id())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    payload = {
        "message": request.message,
        "conversation_id": conversation_id,
        "request_id": task_id,
    }
    creator = getattr(mongo_repository, "create_task", None)
    if creator is not None:
        creator(task_id, payload)
    try:
        task_queue.enqueue(task_id, payload)
    except Exception as exc:
        updater = getattr(mongo_repository, "update_task", None)
        if updater is not None:
            updater(task_id, status="failed", error=f"任务入队失败：{exc}")
        raise HTTPException(status_code=503, detail="任务队列暂时不可用") from exc
    return QueuedTaskResponse(status="queued", task_id=task_id, conversation_id=conversation_id)


@app.get(
    "/ticket/task/{task_id}",
    response_model=TaskStatusResponse,
    response_model_exclude_none=True,
    responses={404: {"description": "任务不存在"}},
)
def get_ticket_task(task_id: str) -> dict:
    """查询后台任务状态和 Worker 写回的结果。"""
    getter = getattr(mongo_repository, "get_task", None)
    task = getter(task_id) if getter is not None else None
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/chat/reset")
def reset_chat_context() -> dict[str, str | bool]:
    """创建一个新的会话 ID，供客户端开始不带历史上下文的对话。"""
    return {"conversation_id": str(uuid.uuid4()), "reset": True}
