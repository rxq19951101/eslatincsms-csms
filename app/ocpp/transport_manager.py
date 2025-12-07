#
# 传输管理器
# 统一管理多种传输方式（WebSocket、HTTP、MQTT）
#

import logging
from typing import Dict, Any, Optional, List
from .transport import (
    TransportAdapter,
    TransportType,
    WebSocketAdapter,
    HTTPAdapter,
    MQTTAdapter
)
from app.core.config import get_settings

logger = logging.getLogger("ocpp_csms")


class TransportManager:
    """传输管理器
    
    支持同时使用多种传输方式：
    - MQTT: 发布-订阅模式（默认通信模式）
    - WebSocket: 实时双向通信
    - HTTP: 请求-响应模式
    """
    
    def __init__(self):
        self.adapters: Dict[TransportType, TransportAdapter] = {}
        self.settings = get_settings()
        self._initialized = False
    
    async def initialize(self, enabled_transports: Optional[List[TransportType]] = None):
        """初始化传输适配器
        
        Args:
            enabled_transports: 启用的传输方式列表，如果为 None 则根据配置自动选择
        """
        if self._initialized:
            logger.warning("传输管理器已初始化，跳过重复初始化")
            return
        
        if enabled_transports is None:
            # 根据配置自动选择启用的传输方式（MQTT 作为默认，仅启用 MQTT）
            enabled_transports = [TransportType.MQTT]  # MQTT 默认启用
            
            # 只在配置启用时才添加其他传输方式（默认不启用）
            if getattr(self.settings, 'enable_websocket_transport', False):
                enabled_transports.append(TransportType.WEBSOCKET)
            
            if getattr(self.settings, 'enable_http_transport', False):
                enabled_transports.append(TransportType.HTTP)
            
            logger.info(f"根据配置自动选择传输方式: {[t.value for t in enabled_transports]}")
        
        # 初始化 WebSocket 适配器
        if TransportType.WEBSOCKET in enabled_transports:
            ws_adapter = WebSocketAdapter()
            await ws_adapter.start()
            self.adapters[TransportType.WEBSOCKET] = ws_adapter
            logger.info("WebSocket 传输已启用")
        
        # 初始化 HTTP 适配器
        if TransportType.HTTP in enabled_transports:
            http_adapter = HTTPAdapter()
            await http_adapter.start()
            self.adapters[TransportType.HTTP] = http_adapter
            logger.info("HTTP 传输已启用")
        
        # 初始化 MQTT 适配器
        if TransportType.MQTT in enabled_transports:
            try:
                mqtt_broker = getattr(self.settings, 'mqtt_broker_host', 'localhost')
                mqtt_port = getattr(self.settings, 'mqtt_broker_port', 1883)
                mqtt_adapter = MQTTAdapter(broker_host=mqtt_broker, broker_port=mqtt_port)
                await mqtt_adapter.start()
                self.adapters[TransportType.MQTT] = mqtt_adapter
                logger.info(f"MQTT 传输已启用，连接到 {mqtt_broker}:{mqtt_port}")
            except ImportError:
                logger.warning("MQTT 传输不可用（paho-mqtt 未安装）")
            except Exception as e:
                logger.error(f"MQTT 传输初始化失败: {e}", exc_info=True)
        
        self._initialized = True
        logger.info(f"传输管理器初始化完成，已启用 {len(self.adapters)} 种传输方式")
    
    async def shutdown(self):
        """关闭所有传输适配器"""
        for transport_type, adapter in self.adapters.items():
            try:
                await adapter.stop()
                logger.info(f"{transport_type.value} 传输已停止")
            except Exception as e:
                logger.error(f"停止 {transport_type.value} 传输时出错: {e}", exc_info=True)
        
        self.adapters.clear()
        self._initialized = False
        logger.info("传输管理器已关闭")
    
    def set_message_handler(self, handler):
        """为所有适配器设置消息处理器"""
        for transport_type, adapter in self.adapters.items():
            adapter.set_message_handler(handler)
            logger.debug(f"{transport_type.value} 适配器已设置消息处理器")
    
    async def send_message(
        self,
        charger_id: str,
        action: str,
        payload: Dict[str, Any],
        preferred_transport: Optional[TransportType] = None,
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """发送消息到充电桩
        
        Args:
            charger_id: 充电桩ID
            action: OCPP动作
            payload: 消息载荷
            preferred_transport: 优先使用的传输方式，如果为 None 则自动选择
            timeout: 超时时间
            
        Returns:
            响应数据
        """
        # 如果指定了传输方式，优先使用
        if preferred_transport and preferred_transport in self.adapters:
            adapter = self.adapters[preferred_transport]
            if adapter.is_connected(charger_id):
                try:
                    return await adapter.send_message(charger_id, action, payload, timeout)
                except Exception as e:
                    logger.warning(f"使用 {preferred_transport.value} 发送失败: {e}")
        
        # 自动选择可用的传输方式
        # 优先级: MQTT > WebSocket > HTTP
        transport_priority = [
            TransportType.MQTT,
            TransportType.WEBSOCKET,
            TransportType.HTTP
        ]
        
        for transport_type in transport_priority:
            if transport_type in self.adapters:
                adapter = self.adapters[transport_type]
                if adapter.is_connected(charger_id):
                    try:
                        return await adapter.send_message(charger_id, action, payload, timeout)
                    except Exception as e:
                        logger.warning(f"使用 {transport_type.value} 发送失败: {e}")
                        continue
        
        # 如果所有方式都失败，尝试使用 HTTP（即使未连接也可以排队）
        if TransportType.HTTP in self.adapters:
            adapter = self.adapters[TransportType.HTTP]
            return await adapter.send_message(charger_id, action, payload, timeout)
        
        raise ConnectionError(f"无法发送消息到充电桩 {charger_id}，所有传输方式都不可用")
    
    def is_connected(self, charger_id: str) -> bool:
        """检查充电桩是否通过任何传输方式连接"""
        for adapter in self.adapters.values():
            if adapter.is_connected(charger_id):
                return True
        return False
    
    def get_connection_type(self, charger_id: str) -> Optional[TransportType]:
        """获取充电桩使用的传输方式"""
        for transport_type, adapter in self.adapters.items():
            if adapter.is_connected(charger_id):
                return transport_type
        return None
    
    def get_adapter(self, transport_type: TransportType) -> Optional[TransportAdapter]:
        """获取指定类型的适配器"""
        return self.adapters.get(transport_type)


# 全局传输管理器实例
transport_manager = TransportManager()

