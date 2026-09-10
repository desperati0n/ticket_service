"""本模块负责组装 FastAPI、仓储和工单业务流程。"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
from pydantic import Field

from .agent import AgentRequest, TicketAgent
from .real_repositories import MongoRepository, MySQLRepository
from .queue import TaskQueue
from .schemas import QueuedTaskResponse, TaskStatusResponse, TicketRequest
from .service import TicketFlow
from .session import SESSION_COOKIE_NAME, ConversationSessionStore

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
mysql_repository = MySQLRepository()
mongo_repository = MongoRepository()
flow = TicketFlow(mysql_repository, mongo_repository)
ticket_agent = TicketAgent(mysql_repository, mongo_repository)
task_queue = TaskQueue()
conversation_sessions = ConversationSessionStore()
TASK_STREAM_POLL_SECONDS = float(os.getenv("TASK_STREAM_POLL_SECONDS", "0.1"))
TASK_STREAM_TIMEOUT_SECONDS = float(os.getenv("TASK_STREAM_TIMEOUT_SECONDS", "300"))

app = FastAPI(
    title=os.getenv("OPENAPI_TITLE", "IT 运维助手 Demo API"),
    description="内部 IT 运维助手的流式后台队列接口。",
    version="0.1.0",
)


def _sse_frame(event: dict) -> str:
    """使用 Chat 接口相同的格式序列化一个 SSE 事件。"""
    return f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

@app.get("/health")
def health() -> dict:
    """返回服务健康状态和运行环境。"""
    return {"status": "ok", "environment": os.getenv("APP_ENV", "development")}


@app.post("/ticket/stream")
def create_ticket_stream(request: TicketRequest) -> StreamingResponse:
    """将结构化工单请求入队，并流式转发 Worker 处理结果。"""
    task = _enqueue_structured_ticket_task(request)
    return _task_streaming_response([task])

@app.post("/chat/stream")
def chat_stream(request: AgentRequest, http_request: Request) -> StreamingResponse:
    """将单条自然语言消息入队，并延续当前浏览器会话。"""
    session_id, is_new_session = _client_session(http_request)
    conversation_id = _single_conversation_id(session_id, request.conversation_id, is_new_session)
    task = _enqueue_one_ticket_task(request, conversation_id=conversation_id)
    return _task_streaming_response([task], session_id=session_id)


@app.post(
    "/ticket/task",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "单条或批量任务的 Chat Agent SSE 事件流",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        503: {"description": "任务队列暂时不可用"},
    },
)
def enqueue_ticket_task(
    request: AgentRequest | Annotated[list[AgentRequest], Field(min_length=1)],
    http_request: Request,
) -> StreamingResponse:
    """单条和批量任务均实时返回各自完整的 Chat 时间线。"""
    session_id, is_new_session = _client_session(http_request)
    if isinstance(request, list):
        _clear_session_conversation(session_id)
        tasks = [
            _enqueue_one_ticket_task(item, conversation_id=str(uuid.uuid4()), force_new_task_id=True)
            for item in request
        ]
    else:
        conversation_id = _single_conversation_id(session_id, request.conversation_id, is_new_session)
        tasks = [_enqueue_one_ticket_task(request, conversation_id=conversation_id)]
    return _task_streaming_response(tasks, session_id=session_id)


def tasks_sse_stream(tasks: list[QueuedTaskResponse]):
    """交错转发所有 Worker 任务的 Agent 事件，事件本身保持 Chat 原样。"""
    for task in tasks:
        yield _sse_frame(
            {
                "seq": 0,
                "step": "queued",
                "status": "success",
                "data": {"task_id": task.task_id},
                "request_id": task.task_id,
                "conversation_id": task.conversation_id,
            }
        )

    getter = getattr(mongo_repository, "get_task", None)
    batch_getter = getattr(mongo_repository, "get_tasks", None)
    deadline = time.monotonic() + TASK_STREAM_TIMEOUT_SECONDS
    sent_events = {task.task_id: 0 for task in tasks}
    finished: set[str] = set()

    while time.monotonic() < deadline:
        active_ids = [task.task_id for task in tasks if task.task_id not in finished]
        current_tasks = batch_getter(active_ids) if batch_getter is not None else {}
        for task in tasks:
            if task.task_id in finished:
                continue

            current = current_tasks.get(task.task_id) if batch_getter is not None else (
                getter(task.task_id) if getter is not None else None
            )
            if current is None:
                yield _sse_frame(
                    {
                        "step": "error",
                        "status": "failed",
                        "data": {"code": "TASK_NOT_FOUND", "message": "任务记录不存在"},
                        "request_id": task.task_id,
                        "conversation_id": task.conversation_id,
                    }
                )
                yield _sse_frame(
                    {
                        "step": "done",
                        "status": "failed",
                        "data": {"success": False, "code": "TASK_NOT_FOUND"},
                        "request_id": task.task_id,
                        "conversation_id": task.conversation_id,
                    }
                )
                finished.add(task.task_id)
                continue

            events = current.get("events") or []
            event_offset = sent_events[task.task_id]
            for event in events[event_offset:]:
                yield _sse_frame(event)
            sent_events[task.task_id] = len(events)

            if current.get("status") in {"success", "failed"}:
                if not any(event.get("step") == "done" for event in events):
                    yield _sse_frame(
                        {
                            "step": "done",
                            "status": "failed",
                            "data": {
                                "success": False,
                                "code": "TASK_FAILED",
                                "message": current.get("error", "任务处理失败"),
                            },
                            "request_id": task.task_id,
                            "conversation_id": task.conversation_id,
                        }
                    )
                finished.add(task.task_id)

        if len(finished) == len(tasks):
            return
        time.sleep(TASK_STREAM_POLL_SECONDS)

    for task in tasks:
        if task.task_id not in finished:
            yield _sse_frame(
                {
                    "step": "done",
                    "status": "failed",
                    "data": {
                        "success": False,
                        "code": "TASK_STREAM_TIMEOUT",
                        "message": "等待任务响应超时，可通过任务 ID 继续查询处理结果",
                    },
                    "request_id": task.task_id,
                    "conversation_id": task.conversation_id,
                }
            )


def _client_session(request: Request) -> tuple[str, bool]:
    """读取可信的服务端会话 Cookie，不存在时创建新会话。"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    return (session_id, False) if session_id else (str(uuid.uuid4()), True)


def _single_conversation_id(session_id: str, requested_id: str | None, is_new_session: bool) -> str:
    """单条请求延续当前会话；新客户端可接入显式提供的会话 ID。"""
    try:
        candidate = (requested_id if is_new_session else None) or str(uuid.uuid4())
        return conversation_sessions.resolve(session_id, candidate)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="会话存储暂时不可用") from exc


def _clear_session_conversation(session_id: str) -> None:
    """批量导入后清空当前会话，确保下一次单条请求换新 ID。"""
    try:
        conversation_sessions.clear(session_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="会话存储暂时不可用") from exc


def _task_streaming_response(
    tasks: list[QueuedTaskResponse],
    *,
    session_id: str | None = None,
) -> StreamingResponse:
    """创建统一的异步任务 SSE 响应，并保存客户端会话 Cookie。"""
    response = StreamingResponse(
        tasks_sse_stream(tasks),
        status_code=status.HTTP_200_OK,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    if session_id is not None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=conversation_sessions.ttl_seconds,
        )
    return response


def _enqueue_one_ticket_task(
    request: AgentRequest,
    *,
    conversation_id: str,
    force_new_task_id: bool = False,
) -> QueuedTaskResponse:
    """生成自然语言任务并写入 Redis Stream。"""
    task_id = str(uuid.uuid4()) if force_new_task_id else (request.request_id or str(uuid.uuid4()))
    payload = {
        "task_type": "agent",
        "message": request.message,
        "conversation_id": conversation_id,
        "request_id": task_id,
    }
    return _enqueue_payload(task_id, conversation_id, payload)


def _enqueue_structured_ticket_task(request: TicketRequest) -> QueuedTaskResponse:
    """将结构化工单流程封装为 Worker 任务。"""
    task_id = request.request_id or str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    payload = request.model_dump(exclude_none=True)
    payload.update({"task_type": "structured", "request_id": task_id})
    return _enqueue_payload(task_id, conversation_id, payload)


def _enqueue_payload(task_id: str, conversation_id: str, payload: dict) -> QueuedTaskResponse:
    """持久化任务状态并将载荷写入 Redis。"""
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
def reset_chat_context(http_request: Request) -> JSONResponse:
    """创建新的当前会话，并同步更新浏览器会话 Cookie。"""
    session_id, _ = _client_session(http_request)
    conversation_id = str(uuid.uuid4())
    try:
        conversation_sessions.set(session_id, conversation_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="会话存储暂时不可用") from exc
    response = JSONResponse({"conversation_id": conversation_id, "reset": True})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=conversation_sessions.ttl_seconds,
    )
    return response
