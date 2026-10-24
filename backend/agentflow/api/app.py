"""
FastAPI 应用入口
"""
import os
import secrets

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from agentflow.api.routes import workflow, agent, message, runs, experiments
from agentflow.api.websocket import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("AgentFlow starting...")

    # 初始化数据库
    try:
        from agentflow.storage import init_db
        init_db()
        print("Database initialized")
    except Exception as e:
        print(f"Database initialization warning: {e}")

    # 恢复持久化的工作流定义（不含密钥；执行时需要重新提供 api_key）
    try:
        from agentflow.api.routes.workflow import restore_workflows
        restore_workflows()
    except Exception as e:
        print(f"Workflow restore warning: {e}")

    yield
    # 关闭时
    print("AgentFlow shutting down...")


# 创建应用
app = FastAPI(
    title="AgentFlow API",
    description="轻量级多 Agent 协作框架",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该设置具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(workflow.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(agent.router, prefix="/api/agents", tags=["agents"])
app.include_router(message.router, prefix="/api/messages", tags=["messages"])
app.include_router(runs.router, prefix="/api", tags=["runs"])
app.include_router(experiments.router, prefix="/api", tags=["experiments"])


@app.middleware("http")
async def api_token_guard(request: Request, call_next):
    """可选本地 API Token（默认不启用）。

    设置 AGENTFLOW_API_TOKEN 后，/api/* 需要 `Authorization: Bearer <token>`；
    每次请求读取环境变量，便于测试与本地临时启用。前端可用 VITE_API_TOKEN 注入。
    /health 与 CORS 预检不受限制。
    """
    token = os.getenv("AGENTFLOW_API_TOKEN", "")
    if (
        token
        and request.url.path.startswith("/api")
        and request.method != "OPTIONS"
    ):
        header = request.headers.get("authorization", "")
        if not secrets.compare_digest(header, f"Bearer {token}"):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "AgentFlow",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_global(websocket: WebSocket):
    """全局 WebSocket 连接"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 可以处理客户端发来的消息
            await manager.send_personal_message(
                {"type": "pong", "message": "Connected to AgentFlow"}, websocket
            )
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.websocket("/ws/{workflow_id}")
async def websocket_workflow(websocket: WebSocket, workflow_id: str):
    """工作流特定 WebSocket 连接"""
    await manager.connect(websocket, workflow_id)
    try:
        while True:
            data = await websocket.receive_text()
            # 回声测试
            await manager.send_personal_message(
                {
                    "type": "pong",
                    "workflow_id": workflow_id,
                    "message": f"Connected to workflow {workflow_id}",
                },
                websocket,
            )
    except WebSocketDisconnect:
        manager.disconnect(websocket, workflow_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agentflow.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
