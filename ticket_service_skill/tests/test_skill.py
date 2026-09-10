from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "it-ticket-operations"


def test_skill_contains_original_agent_system_prompt():
    content = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    expected = """你是 IT 运维工单助手。你的任务是理解用户意图，使用工具完成工单增删改查，并用简洁中文反馈结果。

工作流程：
- 创建：先 verify_employee，再 verify_employee_asset，最后 create_ticket。
- 查询单张工单：调用 get_ticket；查询列表：调用 list_tickets。
- 修改：调用 update_ticket，只传用户要求修改的字段。
- 删除：先调用 delete_ticket（confirmed=false）获取详情并请求确认，用户明确确认后再用 confirmed=true 删除。

规则：缺少必要信息就追问，不猜测；工具失败就根据返回结果处理，不声称成功；员工、资产和工单信息以工具结果为准。"""

    assert expected in content


def test_skill_declares_mcp_dependency():
    metadata = yaml.safe_load((SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))

    dependency = metadata["dependencies"]["tools"][0]
    assert dependency["type"] == "mcp"
    assert dependency["transport"] == "streamable_http"
    assert dependency["url"].endswith("/mcp")
