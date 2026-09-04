"""OpenAPI 规范文件的结构和接口覆盖测试。"""

import json
from pathlib import Path


SPEC_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def test_openapi_spec_is_valid_json_and_declares_api_version():
    """规范文件应可被常见 API 工具直接解析。"""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "IT 运维助手 Demo API"
    assert spec["servers"][0]["url"].endswith(":8000")


def test_openapi_spec_covers_all_fastapi_routes():
    """规范必须覆盖当前 FastAPI 应用公开的四个路由。"""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert set(spec["paths"]) == {"/health", "/ticket/stream", "/chat/stream", "/chat/reset"}
    assert set(spec["paths"]["/health"]) == {"get"}
    assert set(spec["paths"]["/ticket/stream"]) == {"post"}
    assert set(spec["paths"]["/chat/stream"]) == {"post"}
    assert set(spec["paths"]["/chat/reset"]) == {"post"}


def test_streaming_endpoints_document_sse_media_type_and_examples():
    """流式接口应声明 text/event-stream，且包含可复制的请求示例。"""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    for path in ("/ticket/stream", "/chat/stream"):
        operation = spec["paths"][path]["post"]
        response = operation["responses"]["200"]
        assert "text/event-stream" in response["content"]
        assert "x-sse-events" in response
        request_content = operation["requestBody"]["content"]["application/json"]
        assert "example" in request_content or "examples" in request_content


def test_openapi_request_schemas_match_runtime_required_fields():
    """规范应反映结构化报修和 Agent 请求的核心必填字段。"""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]

    assert {"employee_no", "asset_description", "problem_description"} <= set(
        schemas["TicketRequest"]["properties"]
    )
    assert schemas["AgentRequest"]["required"] == ["message"]
