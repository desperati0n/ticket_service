# `ticket_service_skill` Skill/MCP 技术架构

> 对应工程：同级仓库 `ticket_service_skill`
>
> 基线日期：2026-09-10

## 1. 定位与关键顺序

该工程把 Agent 推理与工单后端分离。Skill 由外部宿主加载，外部 LLM 先理解用户意图并决定调用哪个 MCP 工具，工具请求随后才进入 Redis 队列。

核心顺序是：

`用户 → 外部 LLM Agent → Skill 约束 → MCP → Redis 队列 → Backend Worker → MySQL/MongoDB`

因此，这套架构是“先 LLM，后队列”。MCP 前端和 Backend Worker 都不调用 LLM；Worker 只执行白名单内的确定性业务规则。

## 2. 总体架构

### 图 1：外部 LLM 位于队列之前

```mermaid
flowchart LR
    user[员工]
    host[外部 Agent 宿主]
    llm[外部 LLM]
    skill[IT Ticket Skill]
    auth[Bearer Token 校验]
    mcp[MCP Frontend]
    redis[(Redis Streams 与结果键)]
    worker[Backend Worker]
    mysql[(MySQL 业务事实)]
    mongo[(MongoDB 工具审计)]

    user -->|自然语言| host
    host -->|加载规则| skill
    host -->|模型推理| llm
    llm -->|决定工具与参数| host
    host -->|MCP Tool Call| auth
    auth --> mcp
    mcp -->|XADD 并等待| redis
    worker -->|XREADGROUP| redis
    redis -->|命令| worker
    worker -->|参数化业务操作| mysql
    worker -->|写操作审计| mongo
    worker -->|任务结果| redis
    redis -->|ToolResult| mcp
    mcp -->|工具结果| host
    host -->|继续推理或答复| llm
    host -->|自然语言结果| user
```

| 组件 | Skill 工程位置 | 职责 |
| --- | --- | --- |
| Skill | `skills/it-ticket-operations/SKILL.md` | 约束外部 Agent 的工具选择、追问、重试与确认流程 |
| Skill 元数据 | `skills/it-ticket-operations/agents/openai.yaml` | 声明显示信息和 `itTicketService` MCP 依赖 |
| MCP Frontend | `ticket_mcp/server.py` | 鉴权、工具定义、参数入口、入队和等待结果 |
| Queue Facade | `ticket_mcp/queued_service.py` | 生成任务 ID、预分配工单 ID、统一超时和错误语义 |
| Redis Adapter | `ticket_mcp/queue.py` | Stream 命令、短期结果键、Consumer Group 与心跳 |
| Backend Worker | `ticket_mcp/worker.py` | 消费并执行白名单业务操作 |
| TicketService | `ticket_mcp/service.py` | 确定性校验、幂等、CRUD 和审计调用 |
| Repositories | `ticket_mcp/repositories.py` | MySQL 业务数据和 MongoDB 写操作审计 |

## 3. Skill 与外部 Agent

Skill 不是服务器，也不执行 Python 代码。它是外部 Agent 的操作手册，规定：

- 创建必须依次调用 `verify_employee`、`verify_employee_asset`、`create_ticket`。
- 缺少工号、资产或故障现象时追问，不能猜测。
- `ASSET_AMBIGUOUS` 必须向用户展示候选并等待选择。
- 删除先以 `confirmed=false` 获取预览，明确确认后才传 `true`。
- 同一次创建意图的重试复用 `request_id`。
- 对用户展示 `ticket_id`，不能把内部 `task_id` 当工单号。

每次 MCP 工具调用都是一个独立队列任务。前三个创建工具不是 Worker 内的一次长事务，而是外部 LLM 按工具结果依次发起的三个请求。`create_ticket` 会在最终写入前重新校验员工与资产归属，因此前两次调用主要用于对话引导和提前发现错误。

### 图 2：外部 LLM 的工具路由

```mermaid
flowchart TD
    user([用户自然语言]) --> llm{外部 LLM 判断意图}
    llm -->|创建| collect{信息是否完整}
    collect -->|否| ask([向用户追问])
    collect -->|是| employee[调用 verify_employee]
    employee --> employeeOk{员工通过}
    employeeOk -->|否| stop([解释错误并停止])
    employeeOk -->|是| asset[调用 verify_employee_asset]
    asset --> assetResult{资产匹配结果}
    assetResult -->|零个| askAsset([补充资产描述])
    assetResult -->|多个| choose([展示候选并等待选择])
    assetResult -->|唯一| create[调用 create_ticket]
    create --> result([返回 ticket_id 与状态])
    llm -->|查询| query[get_ticket 或 list_tickets]
    llm -->|修改| update[update_ticket]
    llm -->|删除| preview[delete_ticket confirmed=false]
```

## 4. MCP 工具契约

MCP 服务使用 Streamable HTTP `/mcp`，公开 8 个受控工具：

| 工具 | 属性 | 关键语义 |
| --- | --- | --- |
| `verify_employee` | 只读、幂等 | 员工必须存在且为 active |
| `verify_employee_asset` | 只读、幂等 | 返回零个、一个或多个匹配资产 |
| `create_ticket` | 写、幂等 | 预分配 Snowflake `ticket_id`，以 `request_id` 幂等 |
| `get_ticket` | 只读、幂等 | 按正整数工单 ID 查询 |
| `list_tickets` | 只读、幂等 | 可按工号过滤，`limit` 为 1 到 100 |
| `update_ticket` | 写 | 至少修改 `issue` 或 `status` 之一 |
| `delete_ticket` | 破坏性写 | 预览与确认分两次调用 |
| `get_task_result` | 只读、幂等 | 查询超时后仍在执行的原任务 |

统一返回结构：

```json
{
  "ok": true,
  "code": "STABLE_CODE",
  "message": "适合向用户解释的信息",
  "data": {},
  "retryable": false
}
```

关键错误码包括 `TOOL_INPUT_INVALID`、`EMPLOYEE_NOT_FOUND`、`EMPLOYEE_INACTIVE`、`ASSET_NOT_FOUND`、`ASSET_AMBIGUOUS`、`VERIFICATION_EXPIRED`、`IDEMPOTENCY_CONFLICT`、`DELETE_CONFIRMATION_REQUIRED`、`TASK_PENDING`、`QUEUE_UNAVAILABLE` 和 `BACKEND_FAILED`。

## 5. 创建工单时序

### 图 3：先 LLM、后队列的完整创建流程

```mermaid
sequenceDiagram
    title Skill/MCP 创建工单
    participant User
    participant ExternalAgent
    participant LLM
    participant MCP
    participant Redis
    participant Backend
    participant MySQL
    participant MongoDB

    User->>ExternalAgent: 工号、资产和故障描述
    ExternalAgent->>LLM: 理解意图并读取 Skill 规则
    LLM-->>ExternalAgent: 调用 verify_employee
    ExternalAgent->>MCP: verify_employee
    MCP->>Redis: 入队并等待
    Backend->>Redis: XREADGROUP
    Redis-->>Backend: 验证员工命令
    Backend->>MySQL: SELECT employee
    Backend-->>Redis: EMPLOYEE_VERIFIED
    Redis-->>MCP: ToolResult
    MCP-->>ExternalAgent: 员工结果

    ExternalAgent->>LLM: 回填员工结果
    LLM-->>ExternalAgent: 调用 verify_employee_asset
    ExternalAgent->>MCP: verify_employee_asset
    MCP->>Redis: 入队并等待
    Backend->>Redis: XREADGROUP
    Redis-->>Backend: 验证资产命令
    Backend->>MySQL: 查询员工名下资产
    Backend-->>Redis: ASSET_VERIFIED
    Redis-->>MCP: ToolResult
    MCP-->>ExternalAgent: 资产结果

    ExternalAgent->>LLM: 回填资产结果
    LLM-->>ExternalAgent: 调用 create_ticket
    ExternalAgent->>MCP: create_ticket 与 request_id
    MCP->>MCP: 预分配 Snowflake ticket_id
    MCP->>Redis: 入队并等待
    Backend->>Redis: XREADGROUP
    Redis-->>Backend: 创建命令
    Backend->>MySQL: 再校验归属并幂等 INSERT
    Backend->>MongoDB: 写 mcp_tool_call 审计
    Backend-->>Redis: TICKET_CREATED 或已存在
    Redis-->>MCP: ToolResult
    MCP-->>ExternalAgent: ticket_id 与 PENDING
    ExternalAgent->>LLM: 生成最终答复
    LLM-->>User: 工单创建结果
```

## 6. Redis 命令与结果模型

Redis Stream 默认为 `ticket_commands`，Consumer Group 为 `ticket_backends`。MCP 为每次工具调用生成 UUID `task_id`，并使用 `ticket_mcp_task:{task_id}` 保存短期状态和结果。

### 图 4：单次工具任务状态机

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Queued: MCP 写结果键并 XADD
    Queued --> Processing: Backend 领取命令
    Queued --> Unknown: MCP 等待超时且状态缺失
    Processing --> Processing: 心跳续租或超时认领
    Processing --> Success: 写入业务 ToolResult
    Processing --> Failed: Backend 未完成命令
    Queued --> Pending: MCP 等待超时
    Processing --> Pending: MCP 等待超时
    Pending --> Success: 后端稍后完成
    Pending --> Failed: 后端稍后失败
    Success --> [*]
    Failed --> [*]
    Unknown --> [*]
```

`Pending` 是调用方看到的 `TASK_PENDING`，不是 Redis 内新增的持久状态；Redis 中任务仍可能是 `queued` 或 `processing`。结果默认保留 `REDIS_RESULT_TTL_SECONDS`。

创建超时时返回预分配 `ticket_id`，之后直接 `get_ticket(ticket_id)`；其他操作超时返回 `task_id`，之后调用 `get_task_result(task_id)`。不能因超时重复提交写操作。

## 7. 幂等与删除保护

创建时，MCP 先生成 Snowflake `ticket_id`，后端以 `request_id` 唯一约束幂等写入：

- 相同请求与相同内容返回 `TICKET_ALREADY_CREATED`。
- 同一 `request_id` 对应不同员工、资产或故障时返回 `IDEMPOTENCY_CONFLICT`。
- 最终写入前重新校验员工状态和资产归属，变化时返回 `VERIFICATION_EXPIRED`。

### 图 5：删除确认时序

```mermaid
sequenceDiagram
    title 删除工单需要两次独立工具调用
    participant User
    participant ExternalAgent
    participant MCP
    participant Queue
    participant Backend
    participant MySQL

    User->>ExternalAgent: 删除指定工单
    ExternalAgent->>MCP: delete_ticket confirmed=false
    MCP->>Queue: 入队预览任务
    Queue-->>Backend: 预览命令
    Backend->>MySQL: SELECT ticket
    Backend-->>MCP: DELETE_CONFIRMATION_REQUIRED 与详情
    ExternalAgent-->>User: 展示工单并请求确认
    User->>ExternalAgent: 明确确认当前工单
    ExternalAgent->>MCP: delete_ticket confirmed=true
    MCP->>Queue: 入队删除任务
    Queue-->>Backend: 删除命令
    Backend->>MySQL: DELETE ticket
    Backend-->>MCP: TICKET_DELETED
    MCP-->>ExternalAgent: 删除成功
    ExternalAgent-->>User: 确认结果
```

## 8. 数据与安全边界

### 图 6：MCP 工程关系模型

```mermaid
erDiagram
    EMPLOYEES ||--o{ EMPLOYEE_ASSETS : owns
    ASSETS ||--o{ EMPLOYEE_ASSETS : assigned_as
    EMPLOYEES ||--o{ TICKETS : submits
    ASSETS ||--o{ TICKETS : referenced_by

    EMPLOYEES {
        bigint id PK
        varchar employee_no UK
        varchar status
    }
    ASSETS {
        bigint id PK
        varchar asset_code UK
        varchar status
    }
    EMPLOYEE_ASSETS {
        bigint employee_id PK, FK
        bigint asset_id PK, FK
    }
    TICKETS {
        bigint id PK
        varchar request_id UK
        bigint employee_id FK
        bigint asset_id FK
        text issue
        varchar status
        timestamp created_at
        timestamp updated_at
    }
```

该工程的 `tickets.id` 是 MCP 预分配的 Snowflake ID，`request_id` 非空且唯一。MongoDB 只记录 `kind=mcp_tool_call` 的创建、修改和删除审计，不保存外部 Agent 的完整对话。审计失败不会回滚 MySQL，结果通过 `data.audit_logged` 表示。

部署时应保持：

- MCP Frontend 只持有 Redis 连接，不持有 MySQL/MongoDB 密钥。
- Backend Worker 持有数据库连接并只执行白名单操作。
- 远程 MCP 配置强随机 `MCP_BEARER_TOKEN` 和 TLS。
- 多个 MCP 实例使用不同的 `SNOWFLAKE_WORKER_ID`，范围 0 到 31。
- 正式多用户部署使用 OAuth/OIDC 和用户级、工具级授权代替单一静态 Token。

## 9. 配置、部署与测试

关键配置包括 `MCP_HOST/PORT/PUBLIC_URL/BEARER_TOKEN`、Redis Stream/Consumer/TTL、Snowflake Worker ID，以及仅供 Backend 使用的 MySQL/MongoDB 参数。

```powershell
python -m pip install -e ".[test]"
docker compose up -d mysql mongo redis
python -m ticket_mcp.worker
python -m ticket_mcp.server
pytest -q
python C:\Users\Endless\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\it-ticket-operations
```

## 10. 关键源码

- `skills/it-ticket-operations/SKILL.md`：外部 Agent 工作流
- `skills/it-ticket-operations/references/tool-contracts.md`：返回码与副作用
- `skills/it-ticket-operations/agents/openai.yaml`：MCP 依赖声明
- `ticket_mcp/server.py`：工具与鉴权
- `ticket_mcp/queued_service.py`：入队、等待与超时
- `ticket_mcp/queue.py`：Redis 命令和短期结果
- `ticket_mcp/worker.py`：确定性白名单 Worker
- `ticket_mcp/service.py`：业务规则与幂等
- `ticket_mcp/repositories.py`：MySQL 与 MongoDB 审计
- `ticket_mcp/ids.py`：Snowflake ID
