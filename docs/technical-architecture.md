# IT 工单工程技术文档索引

本目录将两个实现拆分为独立文档，避免混淆 Agent、LLM 与队列的先后关系：

- [原项目技术架构](ticket-service.md)：`HTTP → Redis 队列 → Worker → 内置 LLM Agent → 数据库`。
- [Skill/MCP 技术架构](ticket-service-skill.md)：`用户 → 外部 LLM Agent → MCP → Redis 队列 → 确定性 Worker → 数据库`。

两种实现共享 IT 工单领域概念，但属于不同运行形态。前者由服务端 Worker 托管 LLM；后者由外部宿主托管 LLM，MCP 后端不调用模型。

## 代码库边界建议

当前阶段建议继续使用两个独立代码库，而不是合并为一个应用代码库，原因如下：

- Agent 边界相反：原项目在队列后调用 LLM，Skill 形态在队列前由外部 LLM 决定工具调用。
- 部署与密钥不同：原项目 Worker 需要模型密钥；MCP Backend 不需要模型密钥，MCP Frontend 不应持有数据库密钥。
- API 协议不同：一个是 FastAPI/SSE，一个是 Streamable HTTP MCP。
- 数据实现不同：当前工单 ID 分别使用 MySQL 自增与 MCP 预分配 Snowflake ID。
- 发布节奏不同：业务应用与可复用 Agent 接入层可以独立演进和回滚。

如果未来确实需要统一管理，更合适的方式是“单一 monorepo、多个可独立部署包”，而不是把两套入口、Worker 和配置混进同一个 Python 包。可抽取共享的领域契约、状态枚举、错误码和数据库迁移，同时保留 `apps/ticket-service`、`apps/ticket-mcp`、`skills/it-ticket-operations` 等清晰边界。
