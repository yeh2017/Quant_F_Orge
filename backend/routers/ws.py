"""
WebSocket 推送通道
==================
/ws — 全局推送端点，服务端主动向前端推送任务进度、新闻、信号等。
HTTP API 完全保留不变，WebSocket 是额外的推送通道。
"""

import asyncio
import json
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Optional

log = structlog.get_logger("ws")
router = APIRouter()


class ConnectionManager:
    """管理 WebSocket 连接，支持线程安全广播"""

    def __init__(self):
        self.active: List[WebSocket] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        # 捕获主 event loop（首次连接时）
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        log.info("ws_connected", total=len(self.active))

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        log.info("ws_disconnected", total=len(self.active))

    async def _do_broadcast(self, data: str):
        """在主 event loop 中执行实际广播"""
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.active:
                self.active.remove(ws)

    def broadcast_threadsafe(self, message: dict):
        """
        线程安全广播 — 可从任何线程调用。
        后台同步任务在线程池中运行，必须用此方法而非直接 await。
        """
        if not self.active or not self._loop:
            return
        try:
            data = json.dumps(message, ensure_ascii=False, default=str)
            asyncio.run_coroutine_threadsafe(self._do_broadcast(data), self._loop)
        except Exception:
            pass  # best-effort


# 全局单例
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # 保持连接活跃；接收客户端心跳或订阅请求（预留扩展）
            data = await ws.receive_text()
            log.debug("ws_received", data=data[:100])
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
