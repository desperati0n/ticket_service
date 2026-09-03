"""本模块负责组装 FastAPI、仓储和工单业务流程。"""

import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .ids import Snowflake
from .real_repositories import MongoRepository, MySQLRepository
from .schemas import TicketRequest
from .service import TicketFlow
from .settings import get_settings

settings = get_settings()
id_generator = Snowflake()
mysql_repository = MySQLRepository(settings, id_generator)
mongo_repository = MongoRepository(settings)
flow = TicketFlow(mysql_repository, mongo_repository)

app = FastAPI(title=settings.app_name)


def sse_stream(request: TicketRequest):
    """将业务流程事件序列化为 SSE 数据帧。"""
    for event in flow.run(request):
        yield f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
def health() -> dict:
    """返回服务健康状态和运行环境。"""
    return {"status": "ok", "environment": settings.app_env}


@app.post("/ticket/stream")
def create_ticket_stream(request: TicketRequest):
    """创建工单并流式返回每个业务步骤。"""
    return StreamingResponse(sse_stream(request), media_type="text/event-stream")
