from ticket_mcp.config import Settings
from ticket_mcp.server import build_server


def make_settings():
    return Settings(
        mcp_host="127.0.0.1",
        mcp_port=8000,
        mcp_public_url="http://127.0.0.1:8000",
        mcp_bearer_token=None,
        mcp_queue_timeout_seconds=30,
        mcp_queue_poll_interval_seconds=0.1,
        snowflake_worker_id=1,
        redis_url="redis://unused",
        redis_stream="ticket_commands",
        redis_consumer_group="ticket_backends",
        redis_pending_idle_ms=120000,
        redis_heartbeat_interval_seconds=30,
        redis_result_ttl_seconds=86400,
        mysql_host="unused",
        mysql_port=3306,
        mysql_database="unused",
        mysql_user="unused",
        mysql_password="unused",
        mongo_uri="mongodb://unused",
        mongo_database="unused",
        mongo_collection="unused",
    )


async def test_mcp_exposes_expected_tools_without_connecting_databases():
    server = build_server(settings=make_settings(), service_provider=lambda: None)

    tools = await server.list_tools()
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == {
        "verify_employee",
        "verify_employee_asset",
        "create_ticket",
        "get_ticket",
        "list_tickets",
        "update_ticket",
        "delete_ticket",
        "get_task_result",
    }
    assert by_name["get_ticket"].annotations.read_only_hint is True
    assert by_name["create_ticket"].annotations.idempotent_hint is True
    assert by_name["delete_ticket"].annotations.destructive_hint is True
    assert by_name["get_task_result"].annotations.read_only_hint is True
    assert "request_id" in by_name["create_ticket"].input_schema["required"]
    assert by_name["create_ticket"].output_schema["type"] == "object"


async def test_mcp_can_enable_static_bearer_auth():
    settings = make_settings()
    settings = Settings(**{**settings.__dict__, "mcp_bearer_token": "secret-token"})

    server = build_server(settings=settings, service_provider=lambda: None)

    assert server.settings.auth is not None
    assert server.settings.auth.required_scopes == ["tickets:read"]
