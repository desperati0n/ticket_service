from fastapi.testclient import TestClient

from app.main import app, mysql_repository, mongo_repository
from app.cli import prompt_request


client = TestClient(app)


def test_prompt_request_collects_answers():
    answers = iter(["10086", "Dell 显示器", "无法点亮", "y"])
    request = prompt_request(lambda _: next(answers))
    assert request.employee_no == "10086"
    assert request.asset_description == "Dell 显示器"
    assert request.problem_description == "无法点亮"
    assert request.priority == "urgent"


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_settings_load_project_env_from_any_working_directory():
    from app.settings import Settings

    settings = Settings(_env_file="G:/实习/ticket_service/.env.example")
    assert settings.mysql_host == "127.0.0.1"
    assert settings.mongo_database == "ticket_service"


def test_structured_request_stream_creates_ticket():
    before = len(mysql_repository.tickets)
    response = client.post(
        "/ticket/stream",
        json={
            "employee_no": "10086",
            "asset_description": "Dell 显示器",
            "problem_description": "无法点亮",
            "priority": "urgent",
        },
    )
    assert response.status_code == 200
    assert "event: ticket_created" in response.text
    assert "event: done" in response.text
    assert len(mysql_repository.tickets) == before + 1
    assert mysql_repository.tickets[-1]["status"] == "PENDING"
    assert mysql_repository.get_ticket(mysql_repository.tickets[-1]["id"])["priority"] == "urgent"
    assert mongo_repository.logs[-1]["status"] == "success"


def test_unknown_employee_returns_error_event():
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


def test_text_input_is_reserved_for_ai():
    response = client.post("/ticket/stream", json={"input_type": "text", "message": "显示器坏了"})
    assert response.status_code == 200
    assert "AI_NOT_ENABLED" in response.text
