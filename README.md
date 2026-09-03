# IT 运维助手 Demo（无 AI）

这是一个可运行、可迭代的 FastAPI Demo。当前使用结构化字段完成报修流程，保留未来 AI 自然语言入口的边界。

## 启动

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

配置统一放在根目录 `.env`，示例见 `.env.example`。默认 `STORAGE_BACKEND=mysql_mongo`，会使用 `.env` 中的 MySQL/MongoDB 参数连接真实服务；单元测试通过环境变量切换到内存仓储。

如需启动数据库服务：

```powershell
docker compose up -d mysql mongo
```

MySQL 首次创建数据卷时会执行 `mysql/init.sql`，建立三张业务表并写入演示员工/资产数据；MongoDB 只需启动服务，`conversation_logs` 集合会在首次写入时自动创建。

## 请求示例

```powershell
curl -N -X POST http://127.0.0.1:8000/ticket/stream `
  -H "Content-Type: application/json" `
  -d '{"employee_no":"10086","asset_description":"Dell 显示器","problem_description":"无法点亮"}'
```

文本入口暂时只返回 `AI_NOT_ENABLED`，接入 LangChain 后再实现解析。

## 终端交互演示

不想手写 JSON 时，可以直接运行：

```powershell
python -m app.cli
```

程序会依次询问工号、资产和故障描述，并把 SSE 对应的处理步骤打印到终端。

启动后输入 `1` 创建工单，输入 `2` 按工单 ID 查询（输入员工工号也会列出该员工历史工单），输入 `3` 查询全部工单，输入 `0` 退出。终端会打印每个步骤的序号、成功/失败状态、返回数据和异常堆栈。

## 测试

```powershell
pytest -q
```
