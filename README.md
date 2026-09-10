# IT 运维工单服务

面向企业内部报修场景的 FastAPI 服务。员工用自然语言描述资产故障后，请求依次经过 Redis Streams、后台 Worker 和内置 LLM Agent，完成员工/资产校验、工单处理与对话归档。

核心流程：`HTTP → Redis 队列 → Worker → LangChain/LLM Agent → MySQL + MongoDB`

## 快速启动

```powershell
Copy-Item .env.example .env
# 在 .env 中填写 DEEPSEEK_API_KEY
docker compose up -d --build api worker mysql mongo redis
```

启动后可访问 `http://localhost:8000/docs` 查看接口文档。主要接口包括：

- `POST /chat/stream`：自然语言工单对话（SSE）
- `POST /ticket/task`：提交单条或批量任务（SSE）
- `GET /ticket/task/{task_id}`：查询任务状态
- `GET /health`：健康检查

## 测试与文档

```powershell
pytest -q
```

完整设计参见 [技术架构文档](docs/ticket-service.md)，接口规范参见 [OpenAPI](openapi.json)。
