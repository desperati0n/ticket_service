from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    "service": PROJECT_ROOT / "docs" / "ticket-service.md",
    "skill": PROJECT_ROOT / "docs" / "ticket-service-skill.md",
}


def _mermaid_blocks(content: str) -> list[str]:
    return re.findall(r"```mermaid\s+(.*?)```", content, flags=re.DOTALL)


def test_original_service_document_places_queue_before_internal_llm():
    content = DOCUMENTS["service"].read_text(encoding="utf-8")

    flow = "HTTP 请求 → Redis 队列 → Backend Worker → LangChain/LLM Agent"
    assert flow in content
    assert "LLM 位于 Worker 内部" in content
    assert "ticket_tasks" in content
    assert "AUTO_INCREMENT" in content
    assert "Snowflake" not in content
    assert "ticket_service_skill" not in content


def test_skill_document_places_external_llm_before_queue():
    content = DOCUMENTS["skill"].read_text(encoding="utf-8")

    flow = "用户 → 外部 LLM Agent → Skill 约束 → MCP → Redis 队列 → Backend Worker"
    assert flow in content
    assert "这套架构是“先 LLM，后队列”" in content
    assert "MCP 前端和 Backend Worker 都不调用 LLM" in content
    assert "ticket_commands" in content
    assert "Snowflake" in content
    assert "Streamable HTTP" in content


def test_each_document_contains_at_least_four_mermaid_diagrams():
    for document in DOCUMENTS.values():
        content = document.read_text(encoding="utf-8")
        blocks = _mermaid_blocks(content)

        assert len(blocks) >= 4, document
        assert content.count("```mermaid") == len(blocks)
        sources = "\n".join(blocks)
        assert "flowchart" in sources
        assert "sequenceDiagram" in sources
        assert "stateDiagram-v2" in sources
        assert "erDiagram" in sources


def test_index_explains_repository_boundary_recommendation():
    content = (PROJECT_ROOT / "docs" / "technical-architecture.md").read_text(
        encoding="utf-8"
    )

    assert "两个独立代码库" in content
    assert "ticket-service.md" in content
    assert "ticket-service-skill.md" in content
    assert "monorepo、多个可独立部署包" in content
