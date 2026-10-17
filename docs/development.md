# 开发指南

## 运行与配置

优先使用根目录的 `scripts/dev.py`，它检查依赖和端口，并只管理自己启动的两个服务。前端仍有 Vite 热更新；启动器中的后端不自动重载，以避免编辑文件时清空内存工作流。

后端单独开发时，可从 `backend/` 运行：

```bash
python -m uvicorn agentflow.api.app:app --host 127.0.0.1 --port 8000 --reload
```

前端单独运行：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --strictPort
```

前端默认连接 `http://localhost:8000`。可在 `frontend/.env` 设置 `VITE_API_BASE_URL`，改动后重启 Vite。后端目前从创建请求接收模型密钥，不会自动读取根目录 `.env`。

## 前端组织

- `src/components/`：画布、创建弹窗、执行面板、消息时间线和通用交互。
- `src/stores/`：当前工作流、执行同步、删除与消息状态。
- `src/composables/useTimelineResize.js`：拖拽、键盘与高度持久化。
- `src/utils/`：画布映射、选项导航、连接校验和模型选项。
- `src/services/`：HTTP 请求与原生 WebSocket 服务。
- `tests/`：当前启用的 Node 回归测试。

`npm run lint` 只检查；需要自动修正时使用 `npm run lint:fix`。

## 后端组织

- `agentflow/core/`：Agent、Message 和 WorkflowExecutor。
- `agentflow/agents/`：LLM Agent。
- `agentflow/adapters/`：模型接口与工厂。
- `agentflow/api/`：路由和 WebSocket 连接管理。
- `tests/test_api.py`：无需真实密钥的 API 测试。

安装为包时会发现所有 `agentflow.*` 子包。可从项目根目录验证 wheel：

```bash
python -m pip wheel --no-deps ./backend -w .artifacts
```

## 检查与提交

运行前端 lint / test / build 和后端 pytest。上传前运行：

```bash
git add .
python scripts/check_repo.py
git diff --cached --stat
```

检查脚本会拒绝已跟踪的环境文件、缓存、依赖目录、明显凭据串和本地用户路径。它是基础检查，不能替代人工审阅暂存内容。

## 示例

`examples/code_review.py` 使用环境变量读取凭据与模型名。先安装 backend 包，然后在自己的终端设置 `OPENAI_API_KEY` 和 `OPENAI_MODEL` 再运行示例。该示例会调用真实模型，产生对应服务商的使用量。
