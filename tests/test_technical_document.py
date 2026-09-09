from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = PROJECT_ROOT / "docs" / "technical-architecture.md"


def test_technical_document_contains_required_diagrams_and_boundaries():
    content = DOCUMENT.read_text(encoding="utf-8")

    mermaid_blocks = re.findall(r"```mermaid\s+(.*?)```", content, flags=re.DOTALL)
    assert len(mermaid_blocks) >= 4
    assert content.count("```mermaid") == len(mermaid_blocks)

    diagram_sources = "\n".join(mermaid_blocks)
    for diagram_type in ("flowchart", "sequenceDiagram", "erDiagram", "stateDiagram-v2"):
        assert diagram_type in diagram_sources

    for required_term in (
        "ticket_service",
        "ticket_service_skill",
        "Redis Streams",
        "conversation_logs",
        "request_id",
        "ticket_id",
        "TASK_PENDING",
        "DELETE_CONFIRMATION_REQUIRED",
    ):
        assert required_term in content


def test_document_does_not_conflate_the_two_runtime_shapes():
    content = DOCUMENT.read_text(encoding="utf-8")

    assert "两种独立运行形态" in content
    assert "MySQL `AUTO_INCREMENT`" in content
    assert "MCP 前端预分配 Snowflake ID" in content
    assert "不能在未做兼容迁移" in content
