"""AI Agent Mermaid 文档应覆盖全部已注册工具和真实实现文件。"""

from pathlib import Path


FLOWCHART_PATH = Path(__file__).resolve().parents[1] / "docs" / "ai-flowchart.md"


def test_ai_flowchart_documents_every_registered_tool():
    """流程图和速查表不能遗漏 Agent 的任何工具。"""
    source = FLOWCHART_PATH.read_text(encoding="utf-8")
    expected_tools = {
        "verify_employee",
        "verify_employee_asset",
        "create_ticket",
        "get_ticket",
        "list_tickets",
        "update_ticket",
        "delete_ticket",
    }

    assert "app/agent/tools.py" in source
    missing_tools = expected_tools - {tool_name for tool_name in expected_tools if tool_name in source}
    assert not missing_tools
    assert "app/agent/agent.py" in source
    assert "app/main.py" in source
    assert "app/real_repositories.py" in source
    assert "app/operations.py" in source
