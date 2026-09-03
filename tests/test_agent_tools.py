"""独立 Agent Tools 的顺序、校验和防重复行为测试。"""

from app.agent import AgentSessionState, build_ticket_tools


def _tools_by_name(mysql, state=None):
    state = state or AgentSessionState(conversation_id="test-conversation")
    tools = build_ticket_tools(mysql, state)
    return {item.name: item for item in tools}, state


def test_agent_tools_expose_clear_names_and_schemas(repositories):
    """Agent 应只看到边界明确的三个业务 Tool。"""
    mysql, _ = repositories
    tools, _ = _tools_by_name(mysql)

    assert set(tools) == {
        "verify_employee",
        "verify_employee_asset",
        "create_ticket",
        "get_ticket",
        "list_tickets",
        "update_ticket",
        "delete_ticket",
    }
    assert set(tools["verify_employee"].args) == {"employee_no"}
    assert set(tools["verify_employee_asset"].args) == {"asset_description"}
    assert set(tools["create_ticket"].args) == {"problem_description"}
    assert set(tools["get_ticket"].args) == {"ticket_id"}
    assert set(tools["list_tickets"].args) == {"employee_no"}
    assert set(tools["update_ticket"].args) == {"ticket_id", "issue", "status"}
    assert set(tools["delete_ticket"].args) == {"ticket_id", "confirmed"}


def test_agent_tools_support_ticket_crud_operations(repositories):
    """Agent 应能通过独立 Tool 完成工单查询、列表、更新和删除。"""
    mysql, _ = repositories
    tools, _ = _tools_by_name(mysql)
    employee = mysql.get_employee_by_no("10086")
    asset = mysql.assets[0]
    ticket = mysql.create_ticket(employee=employee, asset=asset, issue="旧问题")

    found = tools["get_ticket"].invoke({"ticket_id": ticket["id"]})
    listed = tools["list_tickets"].invoke({"employee_no": "10086"})
    updated = tools["update_ticket"].invoke(
        {"ticket_id": ticket["id"], "issue": "新问题", "status": "IN_PROGRESS"}
    )
    pending_delete = tools["delete_ticket"].invoke({"ticket_id": ticket["id"]})
    deleted = tools["delete_ticket"].invoke({"ticket_id": ticket["id"], "confirmed": True})

    assert found["code"] == "TICKET_FOUND"
    assert listed["data"]["count"] == 1
    assert updated["data"]["ticket"]["status"] == "IN_PROGRESS"
    assert pending_delete["code"] == "DELETE_CONFIRMATION_REQUIRED"
    assert mysql.get_ticket(ticket["id"]) is None
    assert deleted["code"] == "TICKET_DELETED"


def test_agent_tools_enforce_employee_asset_ticket_order(repositories):
    """资产和创建操作必须使用服务器保存的已验证上下文。"""
    mysql, _ = repositories
    tools, state = _tools_by_name(mysql)

    before_employee = tools["verify_employee_asset"].invoke({"asset_description": "Dell 显示器"})
    assert before_employee["code"] == "EMPLOYEE_CONTEXT_REQUIRED"

    employee = tools["verify_employee"].invoke({"employee_no": "10086"})
    asset = tools["verify_employee_asset"].invoke({"asset_description": "Dell"})
    created = tools["create_ticket"].invoke({"problem_description": "无法点亮，急用"})

    assert employee["code"] == "EMPLOYEE_VERIFIED"
    assert asset["code"] == "ASSET_VERIFIED"
    assert created["code"] == "TICKET_CREATED"
    assert created["data"]["status"] == "PENDING"
    assert state.employee is not None
    assert state.asset is not None
    assert state.created_ticket_id == created["data"]["ticket_id"]
    assert mysql.tickets[-1]["issue"] == "无法点亮，急用"


def test_agent_tool_failure_clears_untrusted_context(repositories):
    """工号验证失败后不得保留之前员工及资产的可信状态。"""
    mysql, _ = repositories
    tools, state = _tools_by_name(mysql)
    tools["verify_employee"].invoke({"employee_no": "10086"})
    tools["verify_employee_asset"].invoke({"asset_description": "Dell"})

    failed = tools["verify_employee"].invoke({"employee_no": "404"})

    assert failed["code"] == "EMPLOYEE_NOT_FOUND"
    assert failed["retryable"] is True
    assert state.employee is None
    assert state.asset is None


def test_create_ticket_revalidates_asset_ownership(repositories):
    """创建瞬间必须重新检查资产归属，不能只相信旧的 Agent 上下文。"""
    mysql, _ = repositories
    tools, state = _tools_by_name(mysql)
    tools["verify_employee"].invoke({"employee_no": "10086"})
    tools["verify_employee_asset"].invoke({"asset_description": "Dell"})
    mysql.employee_assets[10086].clear()

    result = tools["create_ticket"].invoke({"problem_description": "无法点亮"})

    assert result["code"] == "ASSET_CONTEXT_EXPIRED"
    assert result["retryable"] is True
    assert state.asset is None
    assert mysql.tickets == []


def test_create_ticket_is_idempotent_within_agent_session(repositories):
    """模型重复调用创建 Tool 时，本次会话不能重复落单。"""
    mysql, _ = repositories
    tools, _ = _tools_by_name(mysql)
    tools["verify_employee"].invoke({"employee_no": "10086"})
    tools["verify_employee_asset"].invoke({"asset_description": "Dell"})

    first = tools["create_ticket"].invoke({"problem_description": "无法点亮"})
    second = tools["create_ticket"].invoke({"problem_description": "无法点亮"})

    assert first["code"] == "TICKET_CREATED"
    assert second["code"] == "TICKET_ALREADY_CREATED"
    assert second["data"]["ticket_id"] == first["data"]["ticket_id"]
    assert len(mysql.tickets) == 1
