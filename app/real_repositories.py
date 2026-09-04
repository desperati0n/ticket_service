"""本模块实现真实 MySQL 业务仓储和 MongoDB 日志仓储。"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from .models import Asset, Employee

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _repair_mojibake(value):
    """兼容旧数据库中把 UTF-8 按 cp1252 保存后的中文文本。"""
    if not isinstance(value, str):
        return value
    for codec in ("cp1252", "latin1"):
        try:
            repaired = value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != value:
            return repaired
    return value


def _repair_row(row):
    """修复查询结果中的历史乱码字段，不影响正常中文。"""
    return {key: _repair_mojibake(value) for key, value in row.items()}


class MySQLRepository:
    """MySQL 仓储负责员工、资产和工单的持久化。"""

    def __init__(self, id_generator):
        """根据环境配置创建 UTF-8 MySQL 连接池。"""
        self._id = id_generator
        user = os.getenv("MYSQL_USER", "ticket_service")
        password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
        host = os.getenv("MYSQL_HOST", "127.0.0.1")
        port = int(os.getenv("MYSQL_PORT", "3306"))
        database = os.getenv("MYSQL_DATABASE", "ticket_service")
        url = f"mysql+pymysql://{quote_plus(user)}:{password}@{host}:{port}/{database}?charset=utf8mb4"
        self.engine = create_engine(url, pool_pre_ping=True, connect_args={"charset": "utf8mb4"})

    def get_employee_by_no(self, employee_no: str) -> Employee | None:
        """按工号查询一名员工。"""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, employee_no, name, department, status FROM employees WHERE employee_no = :no"),
                {"no": employee_no},
            ).mappings().first()
        return Employee(**_repair_row(row)) if row else None

    def verify_asset_belongs_to_employee(self, description: str, employee_id: int) -> Asset | None:
        """确认描述的公司资产已登记，且属于指定员工。"""
        description = _repair_mojibake(description).strip().lower()
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT a.id, a.asset_code, a.name, a.status
                    FROM assets a
                    JOIN employee_assets ea ON ea.asset_id = a.id
                    WHERE ea.employee_id = :employee_id
                """),
                {"employee_id": employee_id},
            ).mappings().all()
        for row in rows:
            asset = Asset(**_repair_row(row))
            name = asset.name.strip().lower()
            code = asset.asset_code.strip().lower()
            if description in name or name in description or description in code or code in description:
                return asset
        return None

    def create_ticket(self, *, employee: Employee, asset: Asset, issue: str) -> dict:
        """向 MySQL 写入一张待处理工单并返回保存值。"""
        if asset is None:
            raise ValueError("asset must be verified before creating a ticket")
        ticket_id = self._id.next_id()
        created_at = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO tickets (id, employee_id, asset_id, issue, status, created_at)
                    VALUES (:id, :employee_id, :asset_id, :issue, 'PENDING', :created_at)
                """),
                {"id": ticket_id, "employee_id": employee.id, "asset_id": asset.id,
                 "issue": issue, "created_at": created_at},
            )
        return {"id": ticket_id, "employee_id": employee.id, "asset_id": asset.id,
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
        return _repair_row(row) if row else None

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
        return [_repair_row(row) for row in rows]

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

    def __init__(self):
        """根据环境配置创建延迟连接的 MongoDB 客户端。"""
        from pymongo import MongoClient

        uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
        database = os.getenv("MONGO_DATABASE", "ticket_service")
        collection = os.getenv("MONGO_COLLECTION", "conversation_logs")
        self.client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        self.collection = self.client[database][collection]

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

    def start_agent_log(self, conversation_id: str, request_id: str, message: str) -> dict:
        """创建一条自然语言 Agent 执行日志。"""
        log = {
            "conversation_id": conversation_id,
            "request_id": request_id,
            "input": {"message": message},
            "events": [],
            "status": "started",
            "created_at": datetime.now(timezone.utc),
        }
        self.collection.insert_one(log)
        return log

    def create_task(self, task_id: str, payload: dict) -> dict:
        """记录一个已接受的异步任务，供状态查询和 Worker 更新。"""
        task = {
            "kind": "async_task",
            "task_id": task_id,
            "input": payload,
            "status": "queued",
            "created_at": datetime.now(timezone.utc),
        }
        self.collection.insert_one(task)
        return task

    def get_task(self, task_id: str) -> dict | None:
        """读取异步任务状态。"""
        return self.collection.find_one({"kind": "async_task", "task_id": task_id}, {"_id": 0})

    def update_task(self, task_id: str, **fields: Any) -> None:
        """更新异步任务状态和处理结果。"""
        fields["updated_at"] = datetime.now(timezone.utc)
        self.collection.update_one(
            {"kind": "async_task", "task_id": task_id},
            {"$set": fields},
        )

    def append_agent_event(self, log: dict, event: dict) -> None:
        """向 Agent 日志追加模型、Tool 或 SSE 事件。"""
        self.collection.update_one(
            {"request_id": log["request_id"]},
            {"$push": {"events": event}},
        )

    def finish_agent_log(
        self,
        log: dict,
        *,
        status: str,
        assistant_message: str | None = None,
        ticket_id: int | None = None,
        error: str | None = None,
    ) -> None:
        """写入 Agent 最终状态，并保存可用于下一轮对话的助手回复。"""
        update: dict[str, Any] = {
            "status": status,
            "ticket_id": ticket_id,
            "updated_at": datetime.now(timezone.utc),
        }
        if assistant_message is not None:
            update["assistant_message"] = assistant_message
        if error:
            update["error"] = error
        self.collection.update_one({"request_id": log["request_id"]}, {"$set": update})

    def get_agent_history(self, conversation_id: str, limit: int = 20) -> list[dict[str, str]]:
        """读取同一会话最近完成的用户消息和助手回复。"""
        rows = (
            self.collection.find(
                {"conversation_id": conversation_id, "status": "success"},
                {"_id": 0, "input.message": 1, "assistant_message": 1, "created_at": 1},
            )
            .sort("created_at", 1)
            .limit(limit)
        )
        history: list[dict[str, str]] = []
        for row in rows:
            message = row.get("input", {}).get("message")
            if message:
                history.append({"role": "user", "content": message})
            assistant_message = row.get("assistant_message")
            if assistant_message:
                history.append({"role": "assistant", "content": assistant_message})
        return history
