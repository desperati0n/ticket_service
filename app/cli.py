from collections.abc import Callable
from pathlib import Path
import sys
import traceback

if __package__ in (None, ""):
    # Support IDEs that run this file directly instead of `python -m app.cli`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.main import flow
    from app.schemas import TicketRequest
else:
    from .main import flow
    from .schemas import TicketRequest


def prompt_request(input_fn: Callable[[str], str] = input) -> TicketRequest:
    """Collect one structured request interactively for the terminal demo."""
    employee_no = input_fn("工号：").strip()
    asset_description = input_fn("哪个资产有问题（例如：Dell 显示器）：").strip()
    problem_description = input_fn("具体问题是什么：").strip()
    urgency = input_fn("是否紧急？输入 y/N：").strip().lower()
    priority = "urgent" if urgency in {"y", "yes", "是", "紧急"} else "normal"
    return TicketRequest(
        employee_no=employee_no,
        asset_description=asset_description,
        problem_description=problem_description,
        priority=priority,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("IT 运维助手 Demo（终端版，无 AI）")
    print("输入 1 创建报修工单，输入 2 查询工单，输入 3 查询所有工单，输入 0 退出。\n")
    while True:
        try:
            choice = input("请选择：").strip()
            if choice == "0":
                print("已退出。")
                return 0
            if choice == "1":
                return create_ticket_interactively()
            if choice == "2":
                return query_ticket_interactively()
            if choice == "3":
                return list_tickets_interactively()
            print("请输入 1、2、3 或 0。")
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return 130


def create_ticket_interactively() -> int:
    print("\n开始创建工单，请依次回答：")
    try:
        request = prompt_request()
        print("\n--- 处理过程 ---")
        for event in flow.run(request):
            data = event["data"]
            label = "SUCCESS" if event["status"] == "success" else "FAILED"
            print(f"[{label}] seq={event['seq']} step={event['step']} data={data}")
        print("--- 处理结束 ---\n")
        return 0
    except Exception as exc:
        print(f"\n[EXCEPTION] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        print("请确认 .env 中的 MySQL/MongoDB 已启动，并检查 STORAGE_BACKEND。")
        return 1


def query_ticket_interactively() -> int:
    try:
        ticket_id = int(input("请输入工单 ID：").strip())
        ticket = flow.mysql.get_ticket(ticket_id)
        if not ticket:
            tickets = flow.mysql.list_tickets(str(ticket_id))
            if tickets:
                print(f"[INFO] 未找到工单 ID，已按员工工号 {ticket_id} 列出历史工单：")
                print_tickets(tickets)
                return 0
            print(f"[FAILED] 找不到工单或员工：{ticket_id}")
            return 1
        print("[SUCCESS] 工单详情：")
        for key, value in ticket.items():
            print(f"  {key}: {value}")
        return 0
    except ValueError:
        print("[FAILED] 工单 ID 必须是数字。")
        return 1
    except Exception as exc:
        print(f"\n[EXCEPTION] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


def list_tickets_interactively() -> int:
    try:
        employee_no = input("员工工号（直接回车查询全部）：").strip() or None
        tickets = flow.mysql.list_tickets(employee_no)
        if not tickets:
            print("[INFO] 没有找到工单。")
            return 0
        print_tickets(tickets)
        return 0
    except Exception as exc:
        print(f"\n[EXCEPTION] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


def print_tickets(tickets: list[dict]) -> None:
    print(f"[SUCCESS] 共 {len(tickets)} 条工单：")
    for ticket in tickets:
        print(
            f"  ID={ticket.get('id')} | 员工={ticket.get('employee_no', ticket.get('employee_id'))} "
            f"| 资产={ticket.get('asset_name', ticket.get('asset_id'))} "
            f"| 优先级={ticket.get('priority')} | 状态={ticket.get('status')} "
            f"| 问题={ticket.get('issue')}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
