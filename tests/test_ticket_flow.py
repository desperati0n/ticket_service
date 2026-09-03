"""工单流程测试覆盖终端输入、API、业务写入和错误分支。"""

from fastapi.testclient import TestClient

from app.main import app
from app.cli import format_event, main as cli_main, prompt_request


client = TestClient(app)


def test_prompt_request_collects_answers():
    """终端输入应被转换成结构化工单请求。"""
    answers = iter(["10086", "Dell 显示器", "无法点亮"])
    request = prompt_request(lambda _: next(answers))
    assert request.employee_no == "10086"
    assert request.asset_description == "Dell 显示器"
    assert request.problem_description == "无法点亮"


def test_health():
    """健康检查应返回正常状态。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_settings_load_project_env_from_any_working_directory():
    """配置应在任意工作目录下读取指定的环境变量文件。"""
    from app.settings import Settings

    settings = Settings(_env_file="G:/实习/ticket_service/.env.example")
    assert settings.mysql_host == "127.0.0.1"
    assert settings.mongo_database == "ticket_service"


def test_structured_request_stream_creates_ticket(repositories):
    """结构化请求应创建待处理工单并完成日志记录。"""
    mysql_repository, mongo_repository = repositories
    before = len(mysql_repository.tickets)
    response = client.post(
        "/ticket/stream",
        json={
            "employee_no": "10086",
            "asset_description": "Dell 显示器",
            "problem_description": "无法点亮",
        },
    )
    assert response.status_code == 200
    assert "event: ticket_created" in response.text
    assert "event: done" in response.text
    assert len(mysql_repository.tickets) == before + 1
    assert mysql_repository.tickets[-1]["status"] == "PENDING"
    assert mysql_repository.get_ticket(mysql_repository.tickets[-1]["id"])["issue"] == "无法点亮"
    assert len(mysql_repository.list_tickets("10086")) >= 1
    assert mongo_repository.logs[-1]["status"] == "success"


def test_unknown_employee_returns_error_event(repositories):
    """不存在的员工应返回明确错误事件且不创建工单。"""
    response = client.post(
        "/ticket/stream",
        json={
            "employee_no": "404",
            "asset_description": "显示器",
            "problem_description": "坏了",
        },
    )
    assert response.status_code == 200
    assert "EMPLOYEE_NOT_FOUND" in response.text
    assert "event: done" not in response.text


def test_text_input_is_reserved_for_ai(repositories):
    """未启用 AI 时自然语言入口应返回保留提示。"""
    response = client.post("/ticket/stream", json={"input_type": "text", "message": "显示器坏了"})
    assert response.status_code == 200
    assert "AI_NOT_ENABLED" in response.text


def test_cli_menu_keeps_running_after_an_operation_choice():
    """菜单操作结束后应回到菜单，而不是直接结束进程。"""
    answers = iter(["9", "0"])
    output = []
    assert cli_main(lambda _: next(answers), output.append) == 0
    assert any("请输入 1、2、3、4、5 或 0" in line for line in output)
    assert output[-1] == "已退出。"


def test_cli_formats_failed_event_without_dumping_mapping():
    """流程失败时应输出摘要，而不是把整个 data 字典打印出来。"""
    message = format_event({
        "seq": 2,
        "step": "employee_lookup",
        "status": "failed",
        "data": {"code": "EMPLOYEE_NOT_FOUND", "message": "employee not found"},
    })
    assert "EMPLOYEE_NOT_FOUND" in message
    assert "employee not found" in message
    assert "{'code'" not in message


def test_test_repository_supports_update_and_delete(repositories):
    """测试仓储替身应支持工单修改和删除。"""
    repository, _ = repositories
    employee = repository.get_employee_by_no("10086")
    ticket = repository.create_ticket(employee=employee, asset=None, issue="旧问题")
    updated = repository.update_ticket(ticket["id"], issue="新问题", status="RESOLVED")
    assert updated["issue"] == "新问题"
    assert updated["status"] == "RESOLVED"
    assert repository.delete_ticket(ticket["id"]) is True
    assert repository.get_ticket(ticket["id"]) is None
    assert repository.delete_ticket(ticket["id"]) is False
