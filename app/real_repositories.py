"""本模块实现真实 MySQL 业务仓储和 MongoDB 日志仓储。"""

from datetime import datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from .models import Asset, Employee


class MySQLRepository:
    """MySQL 仓储负责员工、资产和工单的持久化。"""

    def __init__(self, settings, id_generator):
        """根据环境配置创建 UTF-8 MySQL 连接池。"""
        self._id = id_generator
        password = quote_plus(settings.mysql_password)
        url = f"mysql+pymysql://{quote_plus(settings.mysql_user)}:{password}@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        self.engine = create_engine(url, pool_pre_ping=True, connect_args={"charset": "utf8mb4"})

    def get_employee_by_no(self, employee_no: str) -> Employee | None:
        """按工号查询一名员工。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, employee_no, name, department, status FROM employees WHERE employee_no = :no"),
                {"no": employee_no},
            ).mappings().first()
        return Employee(**row) if row else None

    def find_asset(self, description: str, employee_id: int) -> Asset | None:
        """在员工可用资产中按描述查询一项资产。"""
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

    def create_ticket(self, *, employee: Employee, asset: Asset | None, issue: str) -> dict:
        """向 MySQL 写入一张待处理工单并返回保存值。"""
        ticket_id = self._id.next_id()
        created_at = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO tickets (id, employee_id, asset_id, issue, status, created_at)
                    VALUES (:id, :employee_id, :asset_id, :issue, 'PENDING', :created_at)
                """),
                {"id": ticket_id, "employee_id": employee.id, "asset_id": asset.id if asset else None,
                 "issue": issue, "created_at": created_at},
            )
        return {"id": ticket_id, "employee_id": employee.id, "asset_id": asset.id if asset else None,
                "issue": issue, "status": "PENDING", "created_at": created_at.isoformat()}

    def get_ticket(self, ticket_id: int) -> dict | None:
        """按 ID 查询一张包含关联信息的工单。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT t.id, t.employee_id, e.employee_no, e.name AS employee_name,
                           t.asset_id, a.asset_code, a.name AS asset_name,
                           t.issue, t.status, t.created_at
                    FROM tickets t
                    JOIN employees e ON e.id = t.employee_id
                    LEFT JOIN assets a ON a.id = t.asset_id
                    WHERE t.id = :ticket_id
                """),
                {"ticket_id": ticket_id},
            ).mappings().first()
        return dict(row) if row else None

    def list_tickets(self, employee_no: str | None = None) -> list[dict]:
        """查询工单列表并可按员工工号筛选。"""
        query = """
            SELECT t.id, t.employee_id, e.employee_no, e.name AS employee_name,
                   t.asset_id, a.asset_code, a.name AS asset_name,
                   t.issue, t.status, t.created_at
            FROM tickets t
            JOIN employees e ON e.id = t.employee_id
            LEFT JOIN assets a ON a.id = t.asset_id
        """
        params = {}
        if employee_no:
            query += " WHERE e.employee_no = :employee_no"
            params["employee_no"] = employee_no
        query += " ORDER BY t.created_at DESC"
        with self.engine.connect() as conn:
            rows = conn.execute(text(query), params).mappings().all()
        return [dict(row) for row in rows]

    def update_ticket(self, ticket_id: int, *, issue: str | None = None, status: str | None = None) -> dict | None:
        """更新工单内容或状态，并返回更新后的工单。"""
        changes = {}
        if issue is not None:
            changes["issue"] = issue
        if status is not None:
            changes["status"] = status
        if not changes:
            return self.get_ticket(ticket_id)
        assignments = ", ".join(f"{field} = :{field}" for field in changes)
        changes["ticket_id"] = ticket_id
        with self.engine.begin() as conn:
            conn.execute(text(f"UPDATE tickets SET {assignments} WHERE id = :ticket_id"), changes)
        return self.get_ticket(ticket_id)

    def delete_ticket(self, ticket_id: int) -> bool:
        """删除一张工单，返回是否实际删除。"""
        with self.engine.begin() as conn:
            result = conn.execute(text("DELETE FROM tickets WHERE id = :ticket_id"), {"ticket_id": ticket_id})
        return result.rowcount > 0


class MongoRepository:
    """MongoDB 仓储负责保存请求内容和流程事件。"""

    def __init__(self, settings):
        """根据环境配置创建延迟连接的 MongoDB 客户端。"""
        from pymongo import MongoClient

        self.client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
        self.collection = self.client[settings.mongo_database][settings.mongo_collection]

    def start_log(self, request_id: str, payload: dict) -> dict:
        """将原始请求写入一条新的 MongoDB 文档。"""
        log = {"request_id": request_id, "input": payload, "steps": [], "status": "started"}
        self.collection.insert_one(log)
        return log

    def append_step(self, log: dict, step: dict) -> None:
        """向 MongoDB 文档追加一个流程事件。"""
        self.collection.update_one({"request_id": log["request_id"]}, {"$push": {"steps": step}})

    def finish_log(self, log: dict, *, status: str, ticket_id: int | None = None, error: str | None = None) -> None:
        """将流程最终结果写入 MongoDB 文档。"""
        update = {"status": status, "ticket_id": ticket_id}
        if error:
            update["error"] = error
        self.collection.update_one({"request_id": log["request_id"]}, {"$set": update})
