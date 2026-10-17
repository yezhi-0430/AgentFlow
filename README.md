# AgentFlow

极简黑白风格的本地多智能体工作空间。通过画布创建工作流、配置模型连接、执行任务，并在可调高度的消息时间线中查看过程和结果。

![AgentFlow 工作空间](docs/images/workspace.png)

## 当前功能

- 智能体画布：拖动、缩放、自动布局、详情检查与专注模式。
- 工作流创建与执行：任务输入、状态同步、步骤进度、模型错误提示。
- 工作流删除：二次确认、运行中拦截、清理对应消息与本地选择。
- 消息时间线：拖动底边调整高度、键盘微调、双击恢复与高度记忆。
- 模型连接：提供商选择、OpenRouter 密钥匹配检查。
- 本地编排示例：不调用真实模型，便于先体验界面。

当前稳定使用路径是**顺序执行**。其他模式及服务商的限制见 [当前限制](docs/limitations.md)。

## 本地启动

需要 **Python 3.11+、Node.js 22.13+（22.x）或 24+ 和 npm**。在项目根目录安装依赖：

### Windows PowerShell

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -e "./backend[dev]"
cd frontend
npm ci
cd ..
python scripts/dev.py --check
python scripts/dev.py
```

完成安装后，也可以双击根目录的 `start.bat`。

### macOS / Linux

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e "./backend[dev]"
cd frontend
npm ci
cd ..
python3 scripts/dev.py --check
bash start.sh
```

前端：[http://localhost:5173](http://localhost:5173)
后端文档：[http://localhost:8000/docs](http://localhost:8000/docs)

在启动终端按 **Ctrl+C** 停止本项目启动的服务。端口被占用时，启动器会提示并退出；它不会停止其他 Python 或 Node 进程。

如需更换端口：

```bash
python scripts/dev.py --backend-port 8002 --frontend-port 5176
```

## 模型连接

在页面创建工作流时输入提供商对应的 API Key。使用 OpenRouter 密钥时选择 **OpenRouter**；模型 ID 也应使用该平台支持的格式。

密钥只用于当前后端进程中的模型调用，不写入 Git、浏览器持久存储或配置示例。后端目前使用内存保存工作流与密钥，重启后需重新创建工作流；不要将当前无鉴权的后端直接部署到公网。

前端 API 地址可选配置在 `frontend/.env`，模板见 [frontend/.env.example](frontend/.env.example)。`VITE_` 变量会进入浏览器代码，不能用来存放模型密钥。

## Docker

```bash
docker compose up --build
```

同样访问 5173 和 8000 端口。Compose 仅将端口映射到本机回环地址，按 Ctrl+C 停止。停止后台容器可运行 `docker compose down`。此配置用于本地体验与开发，不包含生产环境的鉴权、持久化或反向代理。

## 检查

```bash
# 项目根目录；先完成后端开发依赖安装
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
# macOS / Linux 使用 backend/.venv/bin/python

cd frontend
npm run lint
npm test
npm run build
```

前端测试使用 Node 自带测试运行器；后端 API 测试使用模拟模型，不消耗 API 额度。GitHub Actions 会运行同样的基础检查。

## 项目结构

```text
backend/              FastAPI、工作流引擎、模型适配器与 API 测试
frontend/             Vue 3、Vite、Pinia、Vue Flow 与前端回归测试
examples/             Python API 使用示例
scripts/              跨平台启动与上传前检查
docs/                 开发、限制、整理说明和 GitHub 上传指南
.github/workflows/    自动检查
```

- [开发指南](docs/development.md)
- [当前限制](docs/limitations.md)
- [上传 GitHub](docs/github.md)
- [本次整理说明](docs/cleanup.md)

## License

沿用项目原有的 [MIT License](LICENSE)，保留原作者声明。
