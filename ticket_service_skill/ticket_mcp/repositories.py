"""MySQL business persistence and MongoDB operation auditing."""

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from .config import Settings
from .models import Asset, Employee


def _json_row(row: Any) -> dict[str, Any]:
    values = dict(row)
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = value.isoformat()
    return values


class MySQLRepository:
    """Execute only parameterized, domain-specific SQL operations."""

    def __init__(self, settings: Settings):
        password = quote_plus(settings.mysql_password)
        user = quote_plus(settings.mysql_user)
        url = (
            f"mysql+pymysql://{user}:{password}@{settings.mysql_host}:"
            f"{settings.mysql_port}/{settings.mysql_database}?charset=utf8mb4"
        )
        self.engine = create_engine(url, pool_pre_ping=True, connect_args={"charset": "utf8mb4"})

    def get_employee_by_no(self, employee_no: str) -> Employee | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id, employee_no, name, department, status "
                    "FROM employees WHERE employee_no = :employee_no"
                ),
                {"employee_no": employee_no},
            ).mappings().first()
        return Employee(**dict(row)) if row else None

    def find_employee_assets(self, employee_id: int, query: str) -> list[Asset]:
        normalized = query.strip().lower()
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT a.id, a.asset_code, a.name, a.status "
                    "FROM assets a "
                    "JOIN employee_assets ea ON ea.asset_id = a.id "
                    "WHERE ea.employee_id = :employee_id"
                ),
                {"employee_id": employee_id},
            ).mappings().all()
        assets = [Asset(**dict(row)) for row in rows]
        return [
            asset
            for asset in assets
            if normalized in asset.name.lower()
            or asset.name.lower() in normalized
            or normalized in asset.asset_code.lower()
            or asset.asset_code.lower() in normalized
        ]

    def create_ticket(
        self,
        *,
        ticket_id: int,
        employee_no: str,
        asset_id: int,
        issue: str,
        request_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Recheck ownership and create once for each request_id."""
        with self.engine.begin() as connection:
            ownership = connection.execute(
                text(
                    "SELECT e.id AS employee_id "
                    "FROM employees e "
                    "JOIN employee_assets ea ON ea.employee_id = e.id "
                    "WHERE e.employee_no = :employee_no AND e.status = 'active' "
                    "AND ea.asset_id = :asset_id"
                ),
                {"employee_no": employee_no, "asset_id": asset_id},
            ).mappings().first()
            if ownership is None:
                raise LookupError("employee or asset ownership changed")

            result = connection.execute(
                text(
                    "INSERT INTO tickets (id, request_id, employee_id, asset_id, issue, status) "
                    "VALUES (:ticket_id, :request_id, :employee_id, :asset_id, :issue, 'PENDING') "
                    "ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)"
                ),
                {
                    "ticket_id": ticket_id,
                    "request_id": request_id,
                    "employee_id": ownership["employee_id"],
                    "asset_id": asset_id,
                    "issue": issue,
                },
            )
            ticket_id = int(result.lastrowid)
            created = result.rowcount == 1
            ticket = self._get_ticket(connection, ticket_id)
            if ticket is None:
                raise RuntimeError("ticket could not be read after insert")
            if (
                ticket["request_id"] != request_id
                or ticket["employee_no"] != employee_no
                or ticket["asset_id"] != asset_id
                or ticket["issue"] != issue
            ):
                raise ValueError("request_id was already used for different ticket data")
        return ticket, created

    def _get_ticket(self, connection: Any, ticket_id: int) -> dict[str, Any] | None:
        row = connection.execute(
            text(
                "SELECT t.id, t.request_id, t.employee_id, e.employee_no, "
                "e.name AS employee_name, t.asset_id, a.asset_code, a.name AS asset_name, "
                "t.issue, t.status, t.created_at, t.updated_at "
                "FROM tickets t JOIN employees e ON e.id = t.employee_id "
                "JOIN assets a ON a.id = t.asset_id WHERE t.id = :ticket_id"
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        return _json_row(row) if row else None

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            return self._get_ticket(connection, ticket_id)

    def list_tickets(self, employee_no: str | None, limit: int) -> list[dict[str, Any]]:
        sql = (
            "SELECT t.id, t.request_id, t.employee_id, e.employee_no, "
            "e.name AS employee_name, t.asset_id, a.asset_code, a.name AS asset_name, "
            "t.issue, t.status, t.created_at, t.updated_at "
            "FROM tickets t JOIN employees e ON e.id = t.employee_id "
            "JOIN assets a ON a.id = t.asset_id"
        )
        params: dict[str, Any] = {"limit": limit}
        if employee_no:
            sql += " WHERE e.employee_no = :employee_no"
            params["employee_no"] = employee_no
        sql += " ORDER BY t.created_at DESC LIMIT :limit"
        with self.engine.connect() as connection:
            rows = connection.execute(text(sql), params).mappings().all()
        return [_json_row(row) for row in rows]

    def update_ticket(
        self,
        ticket_id: int,
        *,
        issue: str | None,
        status: str | None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if issue is not None:
            changes["issue"] = issue
        if status is not None:
            changes["status"] = status
        assignments = ", ".join(f"{field} = :{field}" for field in changes)
        changes["ticket_id"] = ticket_id
        with self.engine.begin() as connection:
            result = connection.execute(
                text(f"UPDATE tickets SET {assignments} WHERE id = :ticket_id"),
                changes,
            )
            if result.rowcount == 0:
                return None
            return self._get_ticket(connection, ticket_id)

    def delete_ticket(self, ticket_id: int) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text("DELETE FROM tickets WHERE id = :ticket_id"),
                {"ticket_id": ticket_id},
            )
        return result.rowcount > 0


class MongoAuditRepository:
    """Store MCP business operation logs without owning the external conversation."""

    def __init__(self, settings: Settings):
        from pymongo import MongoClient

        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
        self.collection = client[settings.mongo_database][settings.mongo_collection]
        self._index_ready = False

    def record(
        self,
        *,
        operation: str,
        request_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> bool:
        try:
            if not self._index_ready:
                self.collection.create_index([("request_id", 1), ("operation", 1)])
                self._index_ready = True
            self.collection.insert_one(
                {
                    "kind": "mcp_tool_call",
                    "operation": operation,
                    "request_id": request_id,
                    "payload": payload,
                    "result": result,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return True
        except Exception:
            return False
