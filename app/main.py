import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .ids import Snowflake
from .repositories import MemoryMongoRepository, MemoryMySQLRepository
from .schemas import TicketRequest
from .service import TicketFlow
from .settings import get_settings

settings = get_settings()
id_generator = Snowflake()
mysql_repository = MemoryMySQLRepository(id_generator)
mongo_repository = MemoryMongoRepository()
flow = TicketFlow(mysql_repository, mongo_repository)

app = FastAPI(title=settings.app_name)


def sse_stream(request: TicketRequest):
    for event in flow.run(request):
        yield f"event: {event['step']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.app_env}


@app.post("/ticket/stream")
def create_ticket_stream(request: TicketRequest):
    return StreamingResponse(sse_stream(request), media_type="text/event-stream")

