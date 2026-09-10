# MCP 工具契约

所有工具返回统一结构：

```json
{
  "ok": true,
  "code": "STABLE_CODE",
  "message": "适合向用户解释的简短信息",
  "data": {},
  "retryable": false
}
```

## 创建流程

1. `verify_employee(employee_no)`：员工不存在或停用时停止。
2. `verify_employee_asset(employee_no, asset_description)`：零匹配时补充描述；多匹配时让用户从 `data.candidates` 中选择。
3. `create_ticket(employee_no, asset_description, problem_description, request_id)`：MCP 使用原项目的雪花算法预分配 `ticket_id`，再由服务端重新验证并以同一 ID 创建 `PENDING` 工单。

`request_id` 是创建幂等键。同一次用户创建意图的超时或网络重试必须复用原值。`TICKET_ALREADY_CREATED` 仍表示成功；`IDEMPOTENCY_CONFLICT` 表示该键已经用于不同内容，不得自动换键后再次创建。

创建成功时，`data.ticket_id` 是对外查询使用的工单 ID。成功结果不返回内部队列 `task_id`。创建等待超时时，`TASK_PENDING` 也会携带预分配的 `data.ticket_id`，稍后使用 `get_ticket(ticket_id)` 查询。

## 查询与修改

- `get_ticket(ticket_id)` 查询单张工单。
- `list_tickets(employee_no?, limit=50)` 查询最近工单，`limit` 最大为 100。
- `update_ticket(ticket_id, issue?, status?, request_id?)` 至少提供一个修改字段。状态只能是 `PENDING`、`IN_PROGRESS`、`RESOLVED`、`CANCELLED`。

## 队列语义

所有业务工具都会先进入 Redis Streams，再由后端处理。创建工具的公开标识始终是 `ticket_id`；其他工具返回 `TASK_PENDING` 时，才从 `data.task_id` 取队列任务 ID，并调用 `get_task_result(task_id)` 查询同一任务。

不要因 `TASK_PENDING` 重复提交写操作。`TASK_NOT_FOUND` 表示任务不存在或结果已超过保留时间；`QUEUE_UNAVAILABLE` 表示队列当前不可用。

## 删除

先调用 `delete_ticket(ticket_id, confirmed=false)` 获取待删除详情。向用户展示工单 ID、资产和故障，再等待明确确认。只有确认属于当前工单时，才调用 `delete_ticket(ticket_id, confirmed=true, request_id?)`。

## 常见错误码

- `TOOL_INPUT_INVALID`：修正参数或追问用户。
- `EMPLOYEE_NOT_FOUND` / `EMPLOYEE_INACTIVE`：停止创建。
- `ASSET_NOT_FOUND` / `ASSET_AMBIGUOUS`：补充或选择资产。
- `VERIFICATION_EXPIRED`：重新执行员工和资产验证。
- `TICKET_NOT_FOUND`：告知用户并核对工单 ID。
- `DELETE_CONFIRMATION_REQUIRED`：等待用户确认，不是系统故障。
- `TASK_PENDING`：使用 `get_task_result` 继续查询原任务。
- `QUEUE_UNAVAILABLE`：告知用户服务暂不可用，不声称业务操作成功。
- `BACKEND_FAILED`：后端未成功处理任务，可在确认当前业务状态后决定是否重试。
