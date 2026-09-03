from collections.abc import Callable
import sys

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
    print("请依次回答问题，系统会实时打印工单处理过程。\n")
    try:
        request = prompt_request()
        for event in flow.run(request):
            data = event["data"]
            if event["status"] == "failed":
                print(f"[ERROR] {event['step']}: {data.get('message', data)}")
                return 1
            print(f"[OK] {event['step']}: {data}")
        print("\n处理结束。")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        return 130
    except Exception as exc:
        print(f"\n数据库连接或处理失败：{exc}")
        print("请确认 .env 中的 MySQL/MongoDB 已启动，并检查 STORAGE_BACKEND。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
