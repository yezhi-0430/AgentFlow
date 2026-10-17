# AgentFlow Backend

FastAPI REST / WebSocket 服务与内存工作流引擎。Python 3.11+。

从项目根目录安装并运行：

```bash
python -m pip install -e "./backend[dev]"
python -m uvicorn agentflow.api.app:app --app-dir backend --host 127.0.0.1 --port 8000
python -m pytest backend/tests -q
```

更推荐使用根目录 README 中的独立虚拟环境。`requirements.txt` 提供同等运行依赖；`pyproject.toml` 负责安装完整 Python 包及可选开发依赖。

工作流与密钥保存在进程内存中，不会持久化。API 文档为 `/docs`，健康检查为 `/health`。API 测试通过模拟适配器覆盖创建、执行、读取消息与删除，不调用真实模型。

其他执行模式、模型服务与部署限制见 [当前限制](../docs/limitations.md)。
