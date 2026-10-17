"""
FastAPI 应用入口
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from agentflow.api.routes import workflow, agent, message
from agentflow.api.websocket import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("AgentFlow starting...")
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
