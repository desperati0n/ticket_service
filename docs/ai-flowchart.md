# AI 工单 Agent 流程图

下面的 Mermaid 图根据当前代码绘制，覆盖 `app/agent/tools.py` 注册的全部工具调用，以及模型路由、SSE 事件、MySQL 持久化和 MongoDB 日志链路。

```mermaid
flowchart LR
    subgraph ingress ["入口与 Agent 编排"]
        user[/员工自然语言请求/]
        api["POST /chat/stream — app/main.py — 接收请求"]
        agent["TicketAgent.run — app/agent/agent.py — 模型与工具循环"]
        model["ChatModel.bind_tools — app/agent/agent.py — 意图识别与路由"]
        budget{"已达 15 次工具上限?"}
        toolResult["工具结果 — app/agent/agent.py — 追加 ToolMessage"]
        answer["最终回复 — app/agent/agent.py — answer/done 事件"]
        sse["agent_sse_stream — app/main.py — 序列化 SSE"]
    end

    subgraph createFlow ["创建工单工具链"]
        verifyEmployee["verify_employee — app/agent/tools.py — 验证工号"]
        verifyAsset["verify_employee_asset — app/agent/tools.py — 验证资产归属"]
        createTicket["create_ticket — app/agent/tools.py — 创建待处理工单"]
    end

    subgraph maintainFlow ["查询与维护工具"]
        getTicket["get_ticket — app/agent/tools.py — 查询工单详情"]
        listTickets["list_tickets — app/agent/tools.py — 查询工单列表"]
        updateTicket["update_ticket — app/agent/tools.py — 修改问题或状态"]
        deletePreview["delete_ticket(false) — app/agent/tools.py — 预览并请求确认"]
        confirmDelete{"用户明确确认删除?"}
        deleteExecute["delete_ticket(true) — app/agent/tools.py — 执行删除"]
    end

    subgraph support ["共享校验与数据层"]
        checks["业务校验 — app/operations.py — 员工、资产、问题校验"]
        mysql[("MySQL — app/real_repositories.py — 员工、资产、工单事实")]
        mongo[("MongoDB conversation_logs — app/real_repositories.py — 对话与事件日志")]
    end

    unknown["未知工具或工具异常 — app/agent/agent.py — 返回失败结果"]
    limitError["tool_limit_reached/error — app/agent/agent.py — 结束本次请求"]
    confirmReply["确认提示 — app/agent/agent.py — 等待用户下一轮输入"]

    user --> api --> agent
    agent --> mongo
    agent --> model
    model -->|"无工具调用"| answer
    model -->|"请求调用工具"| budget
    budget -->|"是"| limitError
    budget -->|"否"| toolRouter{"模型选择工具"}

    toolRouter -->|"创建"| verifyEmployee
    verifyEmployee --> checks
    checks --> mysql
    verifyEmployee -->|"验证成功"| verifyAsset
    verifyAsset --> checks
    verifyAsset -->|"验证成功"| createTicket
    createTicket --> checks
    createTicket -->|"复核通过并写入"| mysql

    toolRouter -->|"查询详情"| getTicket
    getTicket -->|"读取"| mysql
    toolRouter -->|"查询列表"| listTickets
    listTickets -->|"读取"| mysql
    toolRouter -->|"修改"| updateTicket
    updateTicket -->|"读取并更新"| mysql
    toolRouter -->|"删除"| deletePreview
    deletePreview -->|"读取待删详情"| mysql
    deletePreview --> confirmDelete
    confirmDelete -->|"否"| confirmReply
    confirmDelete -->|"是"| deleteExecute
    deleteExecute -->|"删除"| mysql
    toolRouter -->|"无法匹配"| unknown

    verifyEmployee --> toolResult
    verifyAsset --> toolResult
    createTicket --> toolResult
    getTicket --> toolResult
    listTickets --> toolResult
    updateTicket --> toolResult
    deletePreview --> toolResult
    deleteExecute --> toolResult
    unknown --> toolResult
    toolResult --> model
    answer --> sse
    limitError --> sse
    confirmReply --> sse
    sse --> user
```

## 工具调用速查

| 工具 | 实现文件 | 作用 | 关键约束 |
| --- | --- | --- | --- |
| `verify_employee` | `app/agent/tools.py` | 按工号确认员工身份 | 创建工单前必须先调用 |
| `verify_employee_asset` | `app/agent/tools.py` | 确认资产登记且属于当前员工 | 依赖已验证员工 |
| `create_ticket` | `app/agent/tools.py` | 创建 `PENDING` 待处理工单 | 依赖员工、资产和问题描述；会再次复核 |
| `get_ticket` | `app/agent/tools.py` | 按工单 ID 查询详情 | 找不到返回 `TICKET_NOT_FOUND` |
| `list_tickets` | `app/agent/tools.py` | 查询全部或指定员工的工单列表 | 可选 `employee_no` 筛选 |
| `update_ticket` | `app/agent/tools.py` | 修改问题描述或工单状态 | 至少提供一个修改字段 |
| `delete_ticket` | `app/agent/tools.py` | 删除工单 | 首次 `confirmed=false` 预览；用户明确确认后才允许 `true` |

`app/agent/agent.py` 负责绑定工具、循环调用模型、发出 `model_started` / `tool_started` / `tool_finished` / `answer` / `done` 等事件，并把过程交给 `app/main.py` 的 `/chat/stream` 以 SSE 返回。`app/real_repositories.py` 将结构化业务事实写入 MySQL，将 Agent 会话、工具中间步骤和最终状态写入 MongoDB 的 `conversation_logs` 集合。
