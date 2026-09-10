# IT 工单 MCP Server 与 Standalone Skill

本目录提供外部 Agent 接入 IT 工单系统所需的两个独立组件。

| 组件 | 目录 | 职责 |
| --- | --- | --- |
| MCP Server | [`ticket_mcp/`](ticket_mcp/) | 接收工具调用，经 Redis 队列交给 Backend Worker，访问 MySQL 并写 MongoDB 审计 |
| Standalone Skill | [`skills/it-ticket-operations/`](skills/it-ticket-operations/) | 指导外部 LLM 收集信息、选择工具、处理歧义、重试和删除确认 |

完整链路为：

`用户 → 外部 LLM Agent → Standalone Skill → MCP Server → Redis → Backend Worker → MySQL/MongoDB`

LLM 位于外部 Agent 宿主中，发生在队列之前。MCP Server 与 Backend Worker 不包含第二次 LLM 调用。

## 文档

- [MCP Server 技术架构](docs/mcp-server.md)
- [Standalone Skill 与安装包说明](docs/standalone-skill.md)
- [MCP 工具契约](skills/it-ticket-operations/references/tool-contracts.md)
- [客户端安装包](it-ticket-client-bundle-20260908.zip)

## MCP Server 本地运行

复制 `.env.example` 为 `.env`，设置数据库密码；远程使用时还必须设置强随机 `MCP_BEARER_TOKEN`。

```powershell
python -m pip install -e ".[test]"
docker compose up -d mysql mongo redis
python -m ticket_mcp.worker
python -m ticket_mcp.server
```

默认 MCP 地址是 `http://127.0.0.1:8000/mcp`。完整容器环境可执行：

```powershell
docker compose up -d --build
python scripts\smoke_mcp.py
```

## Standalone Skill 安装

不部署 Server 的 Agent 使用者只需下载安装包，按包内 `START-HERE.md` 安装 Skill，并连接管理员提供的 MCP 地址。不要把真实 Token 写进 Skill、配置示例、聊天消息或 Git 仓库。

## 测试

```powershell
pytest -q
python C:\Users\Endless\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\it-ticket-operations
```

## 部署边界

- MCP Frontend 只持有 Redis 连接信息。
- MySQL/MongoDB 凭据只配置给 Backend Worker。
- 创建工单在入队前预分配 Snowflake `ticket_id`。
- 多个 MCP 实例必须使用不同的 `SNOWFLAKE_WORKER_ID`。
- MongoDB 审计失败不会回滚已提交的 MySQL 工单。
