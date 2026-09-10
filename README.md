# IT 运维助手 Demo

这是一个可运行、可迭代的 FastAPI Demo。当前使用结构化字段完成报修流程，保留未来 AI 自然语言入口的边界。

## 启动

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 后台队列模式

所有 HTTP 工单入口都会先写入 Redis Stream，再由后台 Worker 处理。使用 Docker Compose 启动完整服务：

```powershell
docker compose up -d --build api worker mysql mongo redis
```

默认会启动 4 个 Worker，它们使用同一个 Redis Stream Consumer Group 竞争消费任务。可在 `.env` 中通过 `WORKER_REPLICAS` 调整副本数，或临时覆盖：

```powershell
docker compose up -d --build --scale worker=6
```

每个容器以自身 hostname 作为 Consumer 名称。处理中消息会定时刷新所有权；Worker 异常退出后，超过 `REDIS_PENDING_IDLE_MS` 的 Pending 消息会由其他 Worker 自动认领。`REDIS_HEARTBEAT_INTERVAL_SECONDS` 必须小于 Pending 超时时间。工单 ID 由 MySQL 自增生成，并以任务 `request_id` 做唯一约束，保证并发创建和任务重试不会重复落单。已有 MySQL 数据卷会在服务启动时由 `mysql-migrate` 自动升级。

提交单条异步自然语言工单后，接口会先通过 `queued` 事件返回任务 ID，再持续推送处理时间线；LLM 调用、员工/资产校验和 MySQL 建单由 `worker.py` 在后台完成：

```powershell
curl -N -X POST http://127.0.0.1:8000/ticket/task `
  -H "Content-Type: application/json" `
  -d '{"message":"我的 Dell 显示器坏了，工号 10086，急用"}'
```

单条请求会在入队后保持 SSE 连接，将 Worker 产生的 Chat Agent 时间线实时转发回来：

```text
event: queued
data: {"seq":0,"step":"queued","status":"success","data":{"task_id":"123"},"request_id":"123","conversation_id":"yyy"}

event: answer
data: {"seq":9,"step":"answer","status":"success","data":{"message":"报修已提交，工单状态为待处理。"},"request_id":"123","conversation_id":"yyy"}

event: done
data: {"seq":10,"step":"done","status":"success","data":{"success":true,"ticket_id":456},"request_id":"123","conversation_id":"yyy"}
```

同一接口也接受由一条或多条消息组成的 JSON 数组，用于批量导入。数组中的每条消息都会强制生成独立的 UUID `task_id` 和全新的 `conversation_id`；批量入队前还会清除当前客户端会话，因此下一次发送普通 JSON 时也会自动换用新的对话 ID：

```json
[
  {"message":"工号 10001，Dell 显示器无法点亮"},
  {"message":"工号 10005，惠普打印机一直卡纸"}
]
```

批量请求同样返回 `200 text/event-stream`：先为每条消息发送一个 `queued` 事件，再交错推送每个任务原样的 Chat Agent 事件。可通过每个事件中的 `request_id` 和 `conversation_id` 区分所属任务，连接会在所有任务都发送 `done` 后关闭。

普通 JSON 请求会通过 HttpOnly `ticket_session_id` Cookie 在 Redis 中保存当前 `conversation_id`，同一客户端后续发送单条消息时自动延续上下文。首次请求仍可显式传入 `conversation_id` 接入已有对话；之后以后端会话记录为准。`POST /chat/reset` 会立即创建并保存新的对话 ID。

若 SSE 连接中断，可使用其中 `queued` 事件返回的 `task_id` 调用 `GET /ticket/task/{task_id}`，查询 `queued`、`processing`、`success` 或 `failed` 状态。任务结束后，查询结果中的 `answer` 是最终自然语言回复，`events` 包含完整处理事件。`/ticket/task`、`/chat/stream` 和结构化 `/ticket/stream` 都走相同的 Redis 队列与 Worker；同一 `conversation_id` 的自然语言任务会使用 Redis 分布式锁串行执行，不同会话仍可由多个 Worker 并行处理。

配置统一放在根目录 `.env`，示例见 `.env.example`。程序始终使用 `.env` 中的 MySQL/MongoDB 参数连接真实服务；测试中的仓储替身仅位于 `tests/`，不会进入生产代码。

如需启动数据库服务和可视化管理工具：

```powershell
docker compose up -d mysql mongo adminer mongo-express
```

MySQL 首次创建数据卷时会执行 `mysql/init.sql`，建立员工、资产、员工资产关联、工单四张业务表，并写入至少 10 条员工和资产数据；MongoDB 只需启动服务，`conversation_logs` 集合会在首次写入时自动创建。

## 请求示例

项目根目录提供可直接导入 Swagger UI、Postman、Insomnia 等工具的 OpenAPI 规范文件：[`openapi.json`](openapi.json)。导入后将服务器地址设为 `http://127.0.0.1:8000`，即可使用内置示例测试健康检查和两个 SSE 接口。

```powershell
curl -N -X POST http://127.0.0.1:8000/ticket/stream `
  -H "Content-Type: application/json" `
  -d '{"employee_no":"10086","asset_description":"Dell 显示器","problem_description":"无法点亮"}'
```

自然语言入口使用 LangChain Agent，接口为 `POST /chat/stream`。Agent 支持工单增删改查；创建报修时会按照“提取信息 → 验证员工 → 验证员工资产 → 创建待处理工单”的顺序调用工具，最多执行 15 次工具调用。每次模型、工具和最终回复都会通过 SSE 推送，并记录到 MongoDB 的 `conversation_logs` 集合。

准备提交新的工单时，可以调用 `POST /chat/reset` 刷新上下文。接口会返回新的 `conversation_id` 并更新会话 Cookie；继续当前工单时无需重复传 ID。非浏览器客户端需要在连续请求间保存并回传 Cookie。

模型配置示例（统一写入根目录 `.env`）：

```dotenv
MODEL_PROVIDER=deepseek
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Agent 使用 LangChain 的 `init_chat_model` 自动初始化模型，提供商、模型名、API Key 和 URL 均从 `.env` 读取。

自然语言请求示例：

```powershell
curl -N -X POST http://127.0.0.1:8000/chat/stream `
  -H "Content-Type: application/json" `
  -d '{"message":"我的 Dell 显示器坏了，工号 10086，急用"}'
```

原有 `/ticket/stream` 仍用于结构化请求，传入 `input_type=text` 时仍保留未启用 AI 的兼容行为。

## 终端交互演示

```powershell
python -m app.cli
```

程序会依次询问工号、资产和故障描述，并把 SSE 对应的处理步骤打印到终端。

启动后菜单会持续运行：输入 `1` 创建工单，`2` 按工单 ID 查询（输入员工工号也会列出该员工历史工单），`3` 查询工单列表，`4` 修改工单问题或状态，`5` 删除工单，`0` 退出。流程错误会显示为简洁的错误摘要，不再直接打印 JSON 或异常堆栈。

## 测试

```powershell
pytest -q
```
