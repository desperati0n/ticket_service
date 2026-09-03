"""本模块提供工单增删改查和创建流程的终端交互界面。"""

from collections.abc import Callable
from pathlib import Path
import sys

if __package__ in (None, ""):
    # 兼容 IDE 直接运行文件而不是使用 python -m app.cli。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.main import flow
    from app.schemas import TicketRequest
else:
    from .main import flow
    from .schemas import TicketRequest


def prompt_request(input_fn: Callable[[str], str] = input) -> TicketRequest:
    """通过终端提问收集一条结构化工单请求。"""
    employee_no = input_fn("工号：").strip()
    asset_description = input_fn("哪个资产有问题（例如：Dell 显示器）：").strip()
    problem_description = input_fn("具体问题是什么：").strip()
    return TicketRequest(
        employee_no=employee_no,
        asset_description=asset_description,
        problem_description=problem_description,
    )


def main(input_fn: Callable[[str], str] | None = None, output_fn: Callable[[str], None] | None = None) -> int:
    """运行终端菜单直到操作完成或用户退出。"""
    input_fn = input_fn or input
    output_fn = output_fn or print
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    output_fn("IT 运维助手 Demo（终端版，无 AI）")
    output_fn("输入 1 创建，2 查询，3 列出，4 修改，5 删除，0 退出。\n")
    while True:
        try:
            choice = input_fn("请选择：").strip()
            if choice == "0":
                output_fn("已退出。")
                return 0
            if choice == "1":
                create_ticket_interactively(input_fn, output_fn)
            elif choice == "2":
                query_ticket_interactively(input_fn, output_fn)
            elif choice == "3":
                list_tickets_interactively(input_fn, output_fn)
            elif choice == "4":
                update_ticket_interactively(input_fn, output_fn)
            elif choice == "5":
                delete_ticket_interactively(input_fn, output_fn)
            else:
                output_fn("请输入 1、2、3、4、5 或 0。")
        except (KeyboardInterrupt, EOFError):
            output_fn("\n已取消。")
            return 130


def create_ticket_interactively(input_fn: Callable[[str], str] | None = None, output_fn: Callable[[str], None] | None = None) -> None:
    """询问工单信息并打印每个流程事件或异常。"""
    input_fn = input_fn or input
    output_fn = output_fn or print
    output_fn("\n开始创建工单，请依次回答：")
    try:
        request = prompt_request(input_fn)
        output_fn("\n--- 处理过程 ---")
        for event in flow.run(request):
            output_fn(format_event(event))
        output_fn("--- 处理结束 ---\n")
    except Exception as exc:
        print_cli_error(exc, output_fn)


def query_ticket_interactively(input_fn: Callable[[str], str] | None = None, output_fn: Callable[[str], None] | None = None) -> None:
    """按 ID 查询工单，未命中时按员工工号查询历史工单。"""
    input_fn = input_fn or input
    output_fn = output_fn or print
    try:
        ticket_id = int(input_fn("请输入工单 ID：").strip())
        ticket = flow.mysql.get_ticket(ticket_id)
        if not ticket:
            tickets = flow.mysql.list_tickets(str(ticket_id))
            if tickets:
                output_fn(f"[INFO] 未找到工单 ID，已按员工工号 {ticket_id} 列出历史工单：")
                print_tickets(tickets, output_fn)
                return
            output_fn(f"[FAILED] 找不到工单或员工：{ticket_id}")
            return
        output_fn("[SUCCESS] 工单详情：")
        for key, value in ticket.items():
            output_fn(f"  {key}: {value}")
    except ValueError:
        output_fn("[FAILED] 工单 ID 必须是数字。")
    except Exception as exc:
        print_cli_error(exc, output_fn)


def list_tickets_interactively(input_fn: Callable[[str], str] | None = None, output_fn: Callable[[str], None] | None = None) -> None:
    """查询全部工单或按可选员工工号筛选。"""
    input_fn = input_fn or input
    output_fn = output_fn or print
    try:
        employee_no = input_fn("员工工号（直接回车查询全部）：").strip() or None
        tickets = flow.mysql.list_tickets(employee_no)
        if not tickets:
            output_fn("[INFO] 没有找到工单。")
            return
        print_tickets(tickets, output_fn)
    except Exception as exc:
        print_cli_error(exc, output_fn)


VALID_STATUSES = ("PENDING", "IN_PROGRESS", "RESOLVED", "CANCELLED")


def update_ticket_interactively(input_fn: Callable[[str], str] | None = None, output_fn: Callable[[str], None] | None = None) -> None:
    """交互式修改工单的问题描述和状态。"""
    input_fn = input_fn or input
    output_fn = output_fn or print
    try:
        ticket_id = int(input_fn("请输入要修改的工单 ID：").strip())
        current = flow.mysql.get_ticket(ticket_id)
        if not current:
            output_fn(f"[FAILED] 找不到工单：{ticket_id}")
            return
        output_fn(f"当前问题：{current.get('issue')}，当前状态：{current.get('status')}")
        issue = input_fn("新问题描述（直接回车保持不变）：").strip() or None
        status = input_fn(f"新状态（{', '.join(VALID_STATUSES)}，直接回车保持不变）：").strip().upper() or None
        if status and status not in VALID_STATUSES:
            output_fn(f"[FAILED] 状态只能是：{', '.join(VALID_STATUSES)}")
            return
        updated = flow.mysql.update_ticket(ticket_id, issue=issue, status=status)
        output_fn(f"[SUCCESS] 工单 {ticket_id} 已更新。状态：{updated.get('status')}")
    except ValueError:
        output_fn("[FAILED] 工单 ID 必须是数字。")
    except Exception as exc:
        print_cli_error(exc, output_fn)


def delete_ticket_interactively(input_fn: Callable[[str], str] | None = None, output_fn: Callable[[str], None] | None = None) -> None:
    """交互式删除工单，并要求用户确认。"""
    input_fn = input_fn or input
    output_fn = output_fn or print
    try:
        ticket_id = int(input_fn("请输入要删除的工单 ID：").strip())
        if not flow.mysql.get_ticket(ticket_id):
            output_fn(f"[FAILED] 找不到工单：{ticket_id}")
            return
        confirm = input_fn("确认删除？请输入 y/yes：").strip().lower()
        if confirm not in {"y", "yes"}:
            output_fn("[INFO] 已取消删除。")
            return
        if flow.mysql.delete_ticket(ticket_id):
            output_fn(f"[SUCCESS] 工单 {ticket_id} 已删除。")
        else:
            output_fn(f"[FAILED] 删除工单 {ticket_id} 失败。")
    except ValueError:
        output_fn("[FAILED] 工单 ID 必须是数字。")
    except Exception as exc:
        print_cli_error(exc, output_fn)


def format_event(event: dict) -> str:
    """将流程事件转换成适合终端阅读的一行文本。"""
    data = event.get("data") or {}
    prefix = f"seq={event.get('seq')} " if event.get("seq") is not None else ""
    if event.get("status") == "failed":
        code = data.get("code")
        message = data.get("message", "处理失败")
        suffix = f"（{code}）" if code else ""
        return f"[FAILED] {prefix}{event.get('step')}: {message}{suffix}"
    if event.get("step") == "ticket_created":
        return f"[SUCCESS] {prefix}工单已创建：ID={data.get('ticket_id')}，状态={data.get('status')}"
    if event.get("step") == "done":
        return f"[SUCCESS] {prefix}处理完成：工单 ID={data.get('ticket_id')}"
    return f"[SUCCESS] {prefix}{event.get('step')}"


def print_cli_error(exc: Exception, output_fn: Callable[[str], None]) -> None:
    """输出不带 traceback/JSON 的简洁错误信息。"""
    output_fn(f"[EXCEPTION] {type(exc).__name__}: {exc}")
    output_fn("请检查输入和 .env 中的数据库配置。")


def print_tickets(tickets: list[dict], output_fn: Callable[[str], None] | None = None) -> None:
    """为每张工单打印一行精简信息。"""
    output_fn = output_fn or print
    output_fn(f"[SUCCESS] 共 {len(tickets)} 条工单：")
    for ticket in tickets:
        output_fn(
            f"  ID={ticket.get('id')} | 员工={ticket.get('employee_no', ticket.get('employee_id'))} "
            f"| 资产={ticket.get('asset_name', ticket.get('asset_id'))} "
            f"| 状态={ticket.get('status')} | 问题={ticket.get('issue')}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
