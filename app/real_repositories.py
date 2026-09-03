from datetime import datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from .repositories import Asset, Employee


class MySQLRepository:
    def __init__(self, settings, id_generator):
        self._id = id_generator
        password = quote_plus(settings.mysql_password)
        url = f"mysql+pymysql://{quote_plus(settings.mysql_user)}:{password}@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        self.engine = create_engine(url, pool_pre_ping=True)

    def get_employee_by_no(self, employee_no: str) -> Employee | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, employee_no, name, department, status FROM employees WHERE employee_no = :no"),
                {"no": employee_no},
            ).mappings().first()
        return Employee(**row) if row else None

    def find_asset(self, description: str, employee_id: int) -> Asset | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, asset_code, name, assigned_employee_id, status
                    FROM assets
                    WHERE (assigned_employee_id IS NULL OR assigned_employee_id = :employee_id)
                      AND (LOWER(name) LIKE :pattern OR LOWER(asset_code) LIKE :pattern)
                    LIMIT 1
                """),
                {"employee_id": employee_id, "pattern": f"%{description.lower()}%"},
            ).mappings().first()
        return Asset(**row) if row else None

    def create_ticket(self, *, employee: Employee, asset: Asset | None, issue: str, priority: str) -> dict:
        ticket_id = self._id.next_id()
        created_at = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO tickets (id, employee_id, asset_id, issue, priority, status, created_at)
                    VALUES (:id, :employee_id, :asset_id, :issue, :priority, 'PENDING', :created_at)
                """),
                {"id": ticket_id, "employee_id": employee.id, "asset_id": asset.id if asset else None,
                 "issue": issue, "priority": priority, "created_at": created_at},
            )
        return {"id": ticket_id, "employee_id": employee.id, "asset_id": asset.id if asset else None,
                "issue": issue, "priority": priority, "status": "PENDING", "created_at": created_at.isoformat()}

    def get_ticket(self, ticket_id: int) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT t.id, t.employee_id, e.employee_no, e.name AS employee_name,
                           t.asset_id, a.asset_code, a.name AS asset_name,
                           t.issue, t.priority, t.status, t.created_at
                    FROM tickets t
                    JOIN employees e ON e.id = t.employee_id
                    LEFT JOIN assets a ON a.id = t.asset_id
                    WHERE t.id = :ticket_id
                """),
                {"ticket_id": ticket_id},
            ).mappings().first()
        return dict(row) if row else None


class MongoRepository:
    def __init__(self, settings):
        from pymongo import MongoClient

        self.client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
        self.collection = self.client[settings.mongo_database][settings.mongo_collection]

    def start_log(self, request_id: str, payload: dict) -> dict:
        log = {"request_id": request_id, "input": payload, "steps": [], "status": "started"}
        self.collection.insert_one(log)
        return log

    def append_step(self, log: dict, step: dict) -> None:
        self.collection.update_one({"request_id": log["request_id"]}, {"$push": {"steps": step}})

    def finish_log(self, log: dict, *, status: str, ticket_id: int | None = None, error: str | None = None) -> None:
        update = {"status": status, "ticket_id": ticket_id}
        if error:
            update["error"] = error
        self.collection.update_one({"request_id": log["request_id"]}, {"$set": update})
