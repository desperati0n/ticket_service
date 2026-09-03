# IT 运维助手 Demo（无 AI）

这是一个可运行、可迭代的 FastAPI Demo。当前使用结构化字段完成报修流程，保留未来 AI 自然语言入口的边界。

## 启动

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

配置统一放在根目录 `.env`，示例见 `.env.example`。当前 `STORAGE_BACKEND=memory`，无需先启动数据库即可演示 API；MySQL/MongoDB 连接参数已经预留在环境变量中，后续替换 repository 即可接入真实服务。

如需启动数据库服务：

```powershell
docker compose up -d mysql mongo
```

MySQL 首次创建数据卷时会执行 `mysql/init.sql`，建立三张业务表并写入演示员工/资产数据；MongoDB 只需启动服务，`conversation_logs` 集合会在首次写入时自动创建。

## 请求示例

```powershell
curl -N -X POST http://127.0.0.1:8000/ticket/stream `
  -H "Content-Type: application/json" `
  -d '{"employee_no":"10086","asset_description":"Dell 显示器","problem_description":"无法点亮","priority":"urgent"}'
```

文本入口暂时只返回 `AI_NOT_ENABLED`，接入 LangChain 后再实现解析。

## 测试

```powershell
pytest -q
```
