"""Streamable HTTP MCP entrypoint for IT ticket operations."""

from collections.abc import Callable
from functools import lru_cache
import secrets
from typing import Any

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .config import Settings
from .ids import Snowflake
from .queue import RedisTicketQueue
from .queued_service import QueuedTicketService


SERVER_INSTRUCTIONS = (
    "创建工单必须依次确认员工、资产归属和故障描述；create_ticket 会再次执行服务端校验。"
    "create_ticket 入队前使用雪花算法分配 ticket_id；对用户返回 ticket_id，不把 task_id 当工单号。"
    "删除工单第一次必须 confirmed=false，只有用户明确确认后才能以 confirmed=true 重试。"
    "TASK_PENDING 表示任务仍在 Redis 队列中，必须用 get_task_result 查询原 task_id。"
    "不要猜测数据库事实；工具返回失败时不得声称操作成功。"
)


class StaticBearerTokenVerifier:
    """Small internal deployment verifier; replace with OAuth for multi-user authorization."""

    def __init__(self, expected_token: str):
        self.expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self.expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="it-ticket-skill",
            scopes=["tickets:read", "tickets:write"],
        )


@lru_cache(maxsize=1)
def get_service() -> QueuedTicketService:
    settings = Settings.from_env()
    return QueuedTicketService(
        RedisTicketQueue(settings),
        timeout_seconds=settings.mcp_queue_timeout_seconds,
        poll_interval_seconds=settings.mcp_queue_poll_interval_seconds,
        id_generator=Snowflake(settings.snowflake_worker_id),
    )


def build_server(
    *,
    settings: Settings | None = None,
    service_provider: Callable[[], QueuedTicketService] = get_service,
) -> MCPServer:
    settings = settings or Settings.from_env()
    auth_options: dict[str, Any] = {}
    if settings.mcp_bearer_token:
        auth_options = {
            "token_verifier": StaticBearerTokenVerifier(settings.mcp_bearer_token),
            "auth": AuthSettings(
                issuer_url=settings.mcp_public_url,
                resource_server_url=f"{settings.mcp_public_url}/mcp",
                required_scopes=["tickets:read"],
                validate_token_resource=False,
            ),
        }

    server = MCPServer(
        "it-ticket-service",
        title="IT Ticket Service",
        description="Controlled internal employee asset and repair ticket operations.",
        instructions=SERVER_INSTRUCTIONS,
        version="0.1.0",
        **auth_options,
    )

    @server.tool(
        title="验证员工",
        description="根据用户明确提供的工号验证员工。创建工单前必须先调用。",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def verify_employee(employee_no: str) -> dict[str, Any]:
        return service_provider().verify_employee(employee_no)

    @server.tool(
        title="验证员工资产",
        description="验证自然语言描述的资产属于指定员工；创建工单前必须调用。",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def verify_employee_asset(employee_no: str, asset_description: str) -> dict[str, Any]:
        return service_provider().verify_employee_asset(employee_no, asset_description)

    @server.tool(
        title="创建维修工单",
        description=(
            "为已验证员工和资产创建 PENDING 工单。入队前预分配雪花 ticket_id；"
            "request_id 是幂等键，同一次请求重试必须复用它。"
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def create_ticket(
        employee_no: str,
        asset_description: str,
        problem_description: str,
        request_id: str,
    ) -> dict[str, Any]:
        return service_provider().create_ticket(
            employee_no, asset_description, problem_description, request_id
        )

    @server.tool(
        title="查询工单",
        description="根据正整数工单 ID 查询工单详情。",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def get_ticket(ticket_id: int) -> dict[str, Any]:
        return service_provider().get_ticket(ticket_id)

    @server.tool(
        title="查询工单列表",
        description="查询最近工单；可按员工工号筛选，limit 范围为 1 到 100。",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def list_tickets(employee_no: str | None = None, limit: int = 50) -> dict[str, Any]:
        return service_provider().list_tickets(employee_no, limit)

    @server.tool(
        title="修改工单",
        description="修改工单问题描述或状态；只传用户明确要求修改的字段。",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def update_ticket(
        ticket_id: int,
        issue: str | None = None,
        status: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return service_provider().update_ticket(ticket_id, issue, status, request_id)

    @server.tool(
        title="删除工单",
        description=(
            "删除工单。首次调用 confirmed=false 获取详情；仅在用户明确确认后才能传 confirmed=true。"
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def delete_ticket(
        ticket_id: int,
        confirmed: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return service_provider().delete_ticket(ticket_id, confirmed, request_id)

    @server.tool(
        title="查询队列任务结果",
        description="查询此前超时返回的队列 task_id；用于等待原任务，不要重复提交写操作。",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def get_task_result(task_id: str) -> dict[str, Any]:
        return service_provider().get_task_result(task_id)

    return server


mcp = build_server()


def main() -> None:
    settings = Settings.from_env()
    mcp.run(
        transport="streamable-http",
        host=settings.mcp_host,
        port=settings.mcp_port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
