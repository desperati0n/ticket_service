# IT 运维工单平台

这是一个面向企业内部 IT 报修场景的示例项目。员工可以用自然语言描述资产故障，系统完成员工与资产校验、创建维修工单，并记录处理过程。

仓库包含两种独立实现：

| 目录 | 用途 | 核心流程 |
| --- | --- | --- |
| [`ticket_service/`](ticket_service/) | 原始 FastAPI 工单服务 | HTTP → Redis 队列 → Worker → 内置 LLM Agent → 数据库 |
| [`ticket_service_skill/`](ticket_service_skill/) | 外部 Agent 的 Skill 与 MCP 服务 | 外部 LLM Agent → MCP → Redis 队列 → Backend Worker → 数据库 |

## 技术文档索引

### 原项目

- [原项目技术架构](ticket_service/docs/ticket-service.md)
- [启动、接口和使用说明](ticket_service/README.md)
- [OpenAPI 规范](ticket_service/openapi.json)

### Skill 与 MCP

- [MCP Server 技术架构](ticket_service_skill/docs/mcp-server.md)
- [Standalone Skill 与安装包说明](ticket_service_skill/docs/standalone-skill.md)
- [Skill/MCP 工程使用说明](ticket_service_skill/README.md)
- [Skill 客户端安装包](ticket_service_skill/it-ticket-client-bundle-20260908.zip)

`ticket_service_skill/` 中的 `ticket_mcp/` 是 MCP Server 与后端实现；`skills/it-ticket-operations/` 是可以独立安装到 Agent 宿主中的 Skill。两者通过工具契约协作，但部署职责和密钥边界相互独立。
