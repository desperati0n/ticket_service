from pathlib import Path
import json
import re
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_DOCUMENT = PROJECT_ROOT / "docs" / "mcp-server.md"
SKILL_DOCUMENT = PROJECT_ROOT / "docs" / "standalone-skill.md"
SKILL_ROOT = PROJECT_ROOT / "skills" / "it-ticket-operations"
ARCHIVE = PROJECT_ROOT / "it-ticket-client-bundle-20260908.zip"
ARCHIVE_ROOT = "it-ticket-client-bundle-20260908"


def test_readme_separates_mcp_server_and_standalone_skill():
    content = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "MCP Server" in content
    assert "Standalone Skill" in content
    assert "ticket_mcp/" in content
    assert "skills/it-ticket-operations/" in content
    assert "外部 LLM Agent → Standalone Skill → MCP Server → Redis" in content


def test_mcp_document_places_external_llm_before_queue():
    content = MCP_DOCUMENT.read_text(encoding="utf-8")
    flow = "用户 → 外部 LLM Agent → MCP → Redis 队列 → Backend Worker"

    assert flow in content
    assert "MCP 前端和 Backend Worker 都不调用 LLM" in content
    assert "ticket_commands" in content
    assert "Snowflake" in content

    blocks = re.findall(r"```mermaid\s+(.*?)```", content, flags=re.DOTALL)
    assert len(blocks) >= 4
    sources = "\n".join(blocks)
    for diagram_type in ("flowchart", "sequenceDiagram", "stateDiagram-v2", "erDiagram"):
        assert diagram_type in sources


def test_standalone_skill_document_and_archive_are_client_only():
    content = SKILL_DOCUMENT.read_text(encoding="utf-8")
    assert "不包含 MCP Server" in content
    assert "contains_server_source=false" in content
    assert "contains_secrets=false" in content

    with zipfile.ZipFile(ARCHIVE) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(f"{ARCHIVE_ROOT}/manifest.json"))
        archived_skill = archive.read(
            f"{ARCHIVE_ROOT}/skill/it-ticket-operations/SKILL.md"
        ).decode("utf-8")

    assert manifest["contains_server_source"] is False
    assert manifest["contains_secrets"] is False
    assert not any("ticket_mcp/" in name for name in names)
    assert not any(name.endswith("/.env") for name in names)
    assert archived_skill == (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
