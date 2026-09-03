# IT 运维助手 Demo（无 AI）

这是一个可运行、可迭代的 FastAPI Demo。当前使用结构化字段完成报修流程，保留未来 AI 自然语言入口的边界。

## 启动

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

配置统一放在根目录 `.env`，示例见 `.env.example`。程序始终使用 `.env` 中的 MySQL/MongoDB 参数连接真实服务；测试中的仓储替身仅位于 `tests/`，不会进入生产代码。

如需启动数据库服务和可视化管理工具：

```powershell
docker compose up -d mysql mongo adminer mongo-express
```

MySQL 首次创建数据卷时会执行 `mysql/init.sql`，建立员工、资产、员工资产关联、工单四张业务表，并写入至少 10 条员工和资产数据；MongoDB 只需启动服务，`conversation_logs` 集合会在首次写入时自动创建。

## 数据库可视化操作

Compose 会下载并启动两个常用的 Web 管理工具：

| 工具 | 浏览器地址 | 用途 |
| --- | --- | --- |
| Adminer | <http://127.0.0.1:8080> | MySQL 表、SQL 和数据 |
| Mongo Express | <http://127.0.0.1:8081> | MongoDB 数据库和集合 |

Adminer 登录时填写：系统 `MySQL`，服务器 `mysql`（这是 Docker 网络中的服务名），用户名 `ticket_service`，密码取 `.env` 的 `MYSQL_PASSWORD`，数据库 `ticket_service`。如果你另外安装宿主机上的桌面客户端，再使用 `127.0.0.1:3306`。

Mongo Express 使用 `.env` 中的 `MONGO_EXPRESS_USERNAME` / `MONGO_EXPRESS_PASSWORD` 登录，进入后选择 `ticket_service` 数据库和 `conversation_logs` 集合。工具容器通过 Docker 网络中的 `mysql`、`mongo` 服务名连接，和程序使用的宿主机端口连接的是同一份数据。

停止工具但保留数据库数据：

```powershell
docker compose stop adminer mongo-express
```

## 请求示例

项目根目录提供可直接导入 Swagger UI、Postman、Insomnia 等工具的 OpenAPI 规范文件：[`openapi.json`](openapi.json)。导入后将服务器地址设为 `http://127.0.0.1:8000`，即可使用内置示例测试健康检查和两个 SSE 接口。

```powershell
curl -N -X POST http://127.0.0.1:8000/ticket/stream `
  -H "Content-Type: application/json" `
  -d '{"employee_no":"10086","asset_description":"Dell 显示器","problem_description":"无法点亮"}'
```

自然语言入口使用 LangChain Agent，接口为 `POST /chat/stream`。Agent 支持工单增删改查；创建报修时会按照“提取信息 → 验证员工 → 验证员工资产 → 创建待处理工单”的顺序调用工具，最多执行 15 次工具调用。每次模型、工具和最终回复都会通过 SSE 推送，并记录到 MongoDB 的 `conversation_logs` 集合。

模型配置示例（统一写入根目录 `.env`）：

```dotenv
MODEL_PROVIDER=openai       # 例如 openai、anthropic、google_genai、ollama
MODEL_NAME=你的模型名称
OPENAI_API_KEY=你的 API Key
# 使用兼容 OpenAI 协议的服务时可填写
OPENAI_BASE_URL=
```

Agent 使用 LangChain 的 `init_chat_model` 统一初始化模型。切换提供商只需修改 `MODEL_PROVIDER`、`MODEL_NAME` 和对应认证变量；非 OpenAI 提供商还需要安装对应的 LangChain 集成包。

自然语言请求示例：

```powershell
curl -N -X POST http://127.0.0.1:8000/chat/stream `
  -H "Content-Type: application/json" `
  -d '{"message":"我的 Dell 显示器坏了，工号 10086，急用"}'
```

原有 `/ticket/stream` 仍用于结构化请求，传入 `input_type=text` 时仍保留未启用 AI 的兼容行为。

## 终端交互演示

不想手写 JSON 时，可以直接运行：

```powershell
python -m app.cli
```

程序会依次询问工号、资产和故障描述，并把 SSE 对应的处理步骤打印到终端。

启动后菜单会持续运行：输入 `1` 创建工单，`2` 按工单 ID 查询（输入员工工号也会列出该员工历史工单），`3` 查询工单列表，`4` 修改工单问题或状态，`5` 删除工单，`0` 退出。流程错误会显示为简洁的错误摘要，不再直接打印 JSON 或异常堆栈。

## 测试

```powershell
pytest -q
```
