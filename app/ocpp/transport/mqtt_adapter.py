#
# MQTT 传输适配器
# 支持 OCPP 消息通过 MQTT 传输
#

import json
import logging
from typing import Dict, Any, Optional
import asyncio
from .base import TransportAdapter, TransportType

logger = logging.getLogger("ocpp_csms")

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.warning("paho-mqtt 未安装，MQTT 传输不可用")


class MQTTAdapter(TransportAdapter):
    """MQTT 传输适配器
    
    支持 OCPP 消息通过 MQTT 传输
    主题格式:
    - 充电桩发送: ocpp/{charger_id}/requests
    - CSMS 发送: ocpp/{charger_id}/responses
    """
    
    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883):
        super().__init__(TransportType.MQTT)
        if not MQTT_AVAILABLE:
            raise ImportError("paho-mqtt 未安装，请运行: pip install paho-mqtt")
        
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client: Optional[mqtt.Client] = None
        self._connected_chargers: set[str] = set()
        self._pending_responses: Dict[str, Dict[str, Any]] = {}
        self._loop = None
    
    async def start(self) -> None:
        """启动 MQTT 客户端"""
        if not MQTT_AVAILABLE:
            raise ImportError("paho-mqtt 未安装")
        
        self._loop = asyncio.get_event_loop()
        
        # 创建 MQTT 客户端
        self.client = mqtt.Client(client_id="csms_server", protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        # 连接到 MQTT broker
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            
            # 订阅所有充电桩的请求主题
            self.client.subscribe("ocpp/+/requests", qos=1)
            
            logger.info(f"MQTT 传输适配器已启动，连接到 {self.broker_host}:{self.broker_port}")
        except Exception as e:
            logger.error(f"MQTT 连接失败: {e}", exc_info=True)
            raise
    
    async def stop(self) -> None:
        """停止 MQTT 客户端"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self._connected_chargers.clear()
            self._pending_responses.clear()
            logger.info("MQTT 传输适配器已停止")
    
    def _on_connect(self, client: mqtt.Client, userdata, flags, rc):
        """MQTT 连接回调"""
        if rc == 0:
            logger.info("MQTT 连接成功")
        else:
            logger.error(f"MQTT 连接失败，返回码: {rc}")
    
    def _on_message(self, client: mqtt.Client, userdata, msg):
        """MQTT 消息接收回调"""
        try:
            # 解析主题: ocpp/{charger_id}/requests
            topic_parts = msg.topic.split("/")
            if len(topic_parts) != 3:
                logger.warning(f"无效的 MQTT 主题格式: {msg.topic}")
                return
            
            charger_id = topic_parts[1]
            message_type = topic_parts[2]
            
            if message_type == "requests":
                # 充电桩发送的请求
                payload = json.loads(msg.payload.decode())
                action = payload.get("action", "")
                payload_data = payload.get("payload", {})
                
                logger.info(f"[{charger_id}] <- MQTT OCPP {action}")
                
                # 标记充电桩已连接
                self._connected_chargers.add(charger_id)
                
                # 异步处理消息（在事件循环中）
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._handle_message(charger_id, action, payload_data))
                else:
                    loop.run_until_complete(self._handle_message(charger_id, action, payload_data))
            else:
                logger.warning(f"未知的消息类型: {message_type}")
                
        except Exception as e:
            logger.error(f"MQTT 消息处理错误: {e}", exc_info=True)
    
    async def _handle_message(self, charger_id: str, action: str, payload: Dict[str, Any]):
        """处理接收到的消息"""
        response = await self.handle_incoming_message(charger_id, action, payload)
        
        # 发送响应到响应主题
        response_topic = f"ocpp/{charger_id}/responses"
        response_message = {
            "action": action,
            "response": response
        }
        
        if self.client:
            self.client.publish(
                response_topic,
                json.dumps(response_message),
                qos=1
            )
            logger.info(f"[{charger_id}] -> MQTT OCPP {action} Response")
    
    def _on_disconnect(self, client: mqtt.Client, userdata, rc):
        """MQTT 断开连接回调"""
        logger.warning(f"MQTT 断开连接，返回码: {rc}")
    
    async def send_message(
        self,
        charger_id: str,
        action: str,
        payload: Dict[str, Any],
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """发送消息到充电桩"""
        if not self.client:
            raise ConnectionError("MQTT 客户端未连接")
        
        # 发送到请求主题（充电桩会监听此主题）
        request_topic = f"ocpp/{charger_id}/requests"
        message = {
            "action": action,
            "payload": payload,
            "from": "csms"
        }
        
        try:
            result = self.client.publish(
                request_topic,
                json.dumps(message),
                qos=1
            )
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"[{charger_id}] -> MQTT OCPP {action}")
                # MQTT 是异步的，无法直接等待响应
                # 实际应用中需要实现请求-响应匹配机制
                return {"success": True, "message": "Message sent via MQTT"}
            else:
                raise ConnectionError(f"MQTT 发布失败，返回码: {result.rc}")
                
        except Exception as e:
            logger.error(f"[{charger_id}] MQTT 发送错误: {e}", exc_info=True)
            raise
    
    def is_connected(self, charger_id: str) -> bool:
        """检查充电桩是否已连接"""
        return charger_id in self._connected_chargers

