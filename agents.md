1.注意事项
AI不允许改动agents文件
每次改动完成后，都必须创建一个对应的git commit，以便后续追踪和回滚
每次改动后，都必须编写或更新相关测试，并在交付给用户前，确保所有测试和验证全部通过

2.业务场景

本项目是一个内部 IT 运维助手。员工通过自然语言提交资产故障或维修请求，例如：
“我的 Dell 显示器坏了，工号 10086，急用”。系统需要查员工信息、生成维修工单，并归档对话记录。

3.技术栈

MySQL：存储比如员工表(employees)、资产表(assets)、工单主表(tickets)，Agent需要根据工号SELECT出员工数据，并INSERT一条新工单(状态为待处理)；

MongoDB：存储对话历史和工单处理日志（conversation_logs)，因为对话消息是半结构化的(包含用户情绪、工具调用中间步骤)，用MongoDB的灵活Schema直接存JSON;

LangChain：比如定义2个@tool（get_employee_by_id、create_ticket），使用bind_tools绑定给ChatModel，Agent根据用户意图自动路由，注意用户意图的自动匹配哈；

FastAPI：提供比如POST /ticket/stream类似接口，使用SSE将"查数据库到调用大模型再到写回双库"的整个过程流式推送；

4.数据职责

MySQL 保存员工、资产、工单等需要事务和结构化查询的业务事实。 
MongoDB 保存原始对话、情绪/上下文等半结构化字段、工具调用中间步骤及工单处理日志。

5.环境变量与配置

项目配置统一通过根目录 `.env` 注入。不创建 `config.py`。遇到需要修改类型的即用即改，不要写统一改类型的。