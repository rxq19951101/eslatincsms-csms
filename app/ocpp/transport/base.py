#
# 传输层基类
# 定义统一的传输接口
#

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, Callable, Awaitable
import logging

logger = logging.getLogger("ocpp_csms")


class TransportType(str, Enum):
    """传输类型"""
    WEBSOCKET = "websocket"
    HTTP = "http"
    MQTT = "mqtt"


class TransportAdapter(ABC):
    """传输适配器基类
    
    所有传输方式（WebSocket、HTTP、MQTT）都需要实现这个接口
    """
    
    def __init__(self, transport_type: TransportType):
        self.transport_type = transport_type
        self.message_handler: Optional[Callable[[str, str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None
    
    @abstractmethod
    async def start(self) -> None:
        """启动传输服务"""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止传输服务"""
        pass
    
    @abstractmethod
    async def send_message(
        self,
        charger_id: str,
        action: str,
        payload: Dict[str, Any],
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """发送消息到充电桩
        
        Args:
            charger_id: 充电桩ID
            action: OCPP动作名称
            payload: 消息载荷
            timeout: 超时时间（秒）
            
        Returns:
            响应数据
        """
        pass
    
    @abstractmethod
    def is_connected(self, charger_id: str) -> bool:
        """检查充电桩是否已连接"""
        pass
    
    def set_message_handler(
        self,
        handler: Callable[[str, str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ) -> None:
        """设置消息处理器
        
        Args:
            handler: 消息处理函数，接收 (charger_id, action, payload) 返回响应
        """
        self.message_handler = handler
    
    async def handle_incoming_message(
        self,
        charger_id: str,
        action: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理接收到的消息"""
        if not self.message_handler:
            logger.warning(f"[{charger_id}] 未设置消息处理器")
            return {"error": "Message handler not set"}
        
        try:
            return await self.message_handler(charger_id, action, payload)
        except Exception as e:
            logger.error(f"[{charger_id}] 消息处理错误: {e}", exc_info=True)
            return {"error": str(e)}

