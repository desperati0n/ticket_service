from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_separates_mcp_queue_and_database_backend():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    assert set(compose["services"]) == {"mysql", "mongo", "redis", "mcp", "backend"}
    assert compose["services"]["mcp"]["ports"] == ["127.0.0.1:8000:8000"]
    assert set(compose["services"]["mcp"]["depends_on"]) == {"redis"}
    assert "MYSQL_HOST" not in compose["services"]["mcp"]["environment"]
    assert set(compose["services"]["backend"]["depends_on"]) == {"redis", "mysql", "mongo"}
    assert compose["services"]["backend"]["environment"]["MYSQL_HOST"] == "mysql"


def test_project_uses_redis_without_an_internal_agent_or_fastapi():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()

    assert '"redis>=5,<7"' in project
    for dependency in ("fastapi", "langchain"):
        assert dependency not in project


def test_ticket_schema_uses_preallocated_snowflake_ids():
    schema = (ROOT / "mysql" / "init.sql").read_text(encoding="utf-8")

    ticket_table = schema.split("CREATE TABLE IF NOT EXISTS tickets", 1)[1].split(");", 1)[0]
    assert "id BIGINT NOT NULL PRIMARY KEY" in ticket_table
    assert "AUTO_INCREMENT" not in ticket_table
