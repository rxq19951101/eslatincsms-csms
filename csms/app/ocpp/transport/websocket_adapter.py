#
# WebSocket 传输适配器
# 支持 OCPP 消息通过 WebSocket 传输
#

import json
import logging
from typing import Dict, Any
from fastapi import WebSocket
from .base import TransportAdapter, TransportType

logger = logging.getLogger("ocpp_csms")


class WebSocketAdapter(TransportAdapter):
    """WebSocket 传输适配器
    
    支持 OCPP 消息通过 WebSocket 双向传输
    """
    
    def __init__(self):
        super().__init__(TransportType.WEBSOCKET)
        self._connections: Dict[str, WebSocket] = {}
    
    async def start(self) -> None:
        """启动 WebSocket 服务（由 FastAPI 管理）"""
        logger.info("WebSocket 传输适配器已初始化")
    
    async def stop(self) -> None:
        """停止 WebSocket 服务"""
        # 关闭所有连接
        for charger_id, ws in list(self._connections.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()
        logger.info("WebSocket 传输适配器已停止")
    
    async def register_connection(self, charger_id: str, websocket: WebSocket) -> None:
        """注册 WebSocket 连接"""
        self._connections[charger_id] = websocket
        logger.info(f"[{charger_id}] WebSocket 连接已注册")
    
    async def unregister_connection(self, charger_id: str) -> None:
        """注销 WebSocket 连接"""
        if charger_id in self._connections:
            del self._connections[charger_id]
            logger.info(f"[{charger_id}] WebSocket 连接已注销")
    
    async def send_message(
        self,
        charger_id: str,
        action: str,
        payload: Dict[str, Any],
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """发送消息到充电桩"""
        ws = self._connections.get(charger_id)
        if not ws:
            raise ConnectionError(f"Charger {charger_id} is not connected via WebSocket")
        
        try:
            message = {
                "action": action,
                "payload": payload
            }
            await ws.send_text(json.dumps(message))
            logger.info(f"[{charger_id}] -> WebSocket OCPP {action}")
            
            # 等待响应（简化版本，实际应该使用消息ID匹配）
            import asyncio
            try:
                response_text = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
                response = json.loads(response_text)
                return {"success": True, "data": response}
            except asyncio.TimeoutError:
                logger.warning(f"[{charger_id}] WebSocket 响应超时: {action}")
                return {"success": False, "error": "Timeout waiting for response"}
                
        except Exception as e:
            logger.error(f"[{charger_id}] WebSocket 发送错误: {e}", exc_info=True)
            raise
    
    def is_connected(self, charger_id: str) -> bool:
        """检查充电桩是否已连接"""
        return charger_id in self._connections

