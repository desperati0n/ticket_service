from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONOREPO_ROOT = PROJECT_ROOT.parent
DOCUMENT = PROJECT_ROOT / "docs" / "ticket-service.md"


def test_original_service_document_places_queue_before_internal_llm():
    content = DOCUMENT.read_text(encoding="utf-8")

    flow = "HTTP 请求 → Redis 队列 → Backend Worker → LangChain/LLM Agent"
    assert flow in content
    assert "LLM 位于 Worker 内部" in content
    assert "ticket_tasks" in content
    assert "AUTO_INCREMENT" in content
    assert "Snowflake" not in content


def test_original_service_document_contains_required_diagrams():
    content = DOCUMENT.read_text(encoding="utf-8")
    blocks = re.findall(r"```mermaid\s+(.*?)```", content, flags=re.DOTALL)

    assert len(blocks) >= 4
    assert content.count("```mermaid") == len(blocks)
    sources = "\n".join(blocks)
    for diagram_type in ("flowchart", "sequenceDiagram", "stateDiagram-v2", "erDiagram"):
        assert diagram_type in sources


def test_monorepo_readme_indexes_both_implementations():
    content = (MONOREPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "ticket_service/" in content
    assert "ticket_service_skill/" in content
    assert "ticket_service/docs/ticket-service.md" in content
    assert "ticket_service_skill/docs/mcp-server.md" in content
    assert "ticket_service_skill/docs/standalone-skill.md" in content


def test_monorepo_has_two_component_directories():
    assert PROJECT_ROOT.is_dir()
    assert (MONOREPO_ROOT / "ticket_service_skill").is_dir()
