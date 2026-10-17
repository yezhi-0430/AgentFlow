"""
WebSocket 支持
"""
import asyncio
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
import json


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # workflow_id -> set of websockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.global_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, workflow_id: str = None):
        """连接客户端"""
        await websocket.accept()

        if workflow_id:
            if workflow_id not in self.active_connections:
                self.active_connections[workflow_id] = set()
            self.active_connections[workflow_id].add(websocket)
        else:
            self.global_connections.add(websocket)

    def disconnect(self, websocket: WebSocket, workflow_id: str = None):
        """断开客户端连接"""
        if workflow_id and workflow_id in self.active_connections:
            self.active_connections[workflow_id].discard(websocket)
            if not self.active_connections[workflow_id]:
                del self.active_connections[workflow_id]
        else:
            self.global_connections.discard(websocket)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """发送个人消息"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"Error sending personal message: {e}")

    async def broadcast_to_workflow(self, workflow_id: str, message: dict):
        """广播消息到特定工作流的所有连接"""
        if workflow_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[workflow_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.add(connection)

            # 清理断开的连接
            for conn in disconnected:
                self.active_connections[workflow_id].discard(conn)

    async def broadcast_global(self, message: dict):
        """全局广播"""
        disconnected = set()
        for connection in self.global_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # 清理断开的连接
        for conn in disconnected:
            self.global_connections.discard(conn)

    async def notify_workflow_event(self, workflow_id: str, event_type: str, data: dict):
        """通知工作流事件"""
        message = {
            "type": "workflow_event",
            "event": event_type,
            "workflow_id": workflow_id,
            "data": data,
        }
        await self.broadcast_to_workflow(workflow_id, message)
        await self.broadcast_global(message)

    async def notify_agent_event(self, workflow_id: str, agent_name: str, event_type: str, data: dict):
        """通知 agent 事件"""
        message = {
            "type": "agent_event",
            "event": event_type,
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "data": data,
        }
        await self.broadcast_to_workflow(workflow_id, message)

    async def notify_message_event(self, workflow_id: str, message_data: dict):
        """通知消息事件"""
        message = {
            "type": "message_event",
            "workflow_id": workflow_id,
            "data": message_data,
        }
        await self.broadcast_to_workflow(workflow_id, message)


# 全局连接管理器实例
manager = ConnectionManager()
