#
# OCPP连接管理
# 管理充电桩WebSocket连接
#

from typing import Dict, Optional
from fastapi import WebSocket
import logging

logger = logging.getLogger("ocpp_csms")


class ConnectionManager:
    """OCPP WebSocket连接管理器"""
    
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
    
    def connect(self, charger_id: str, websocket: WebSocket):
        """注册连接"""
        self._connections[charger_id] = websocket
        logger.info(f"[{charger_id}] WebSocket连接已注册")
    
    def disconnect(self, charger_id: str):
        """断开连接"""
        if charger_id in self._connections:
            del self._connections[charger_id]
            logger.info(f"[{charger_id}] WebSocket连接已断开")
    
    def get_connection(self, charger_id: str) -> Optional[WebSocket]:
        """获取连接"""
        return self._connections.get(charger_id)
    
    def is_connected(self, charger_id: str) -> bool:
        """检查是否连接"""
        return charger_id in self._connections
    
    def get_all_charger_ids(self) -> list:
        """获取所有已连接的充电桩ID"""
        return list(self._connections.keys())
    
    def count(self) -> int:
        """获取连接数"""
        return len(self._connections)


# 全局连接管理器实例
connection_manager = ConnectionManager()

