#
# 分布式连接管理器
# 支持多服务器部署，使用Redis共享连接状态
#

import json
import socket
import uuid
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from fastapi import WebSocket
import redis
from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger("ocpp_csms")

settings = get_settings()


class DistributedConnectionManager:
    """分布式WebSocket连接管理器
    
    支持多服务器部署：
    - 使用Redis存储连接状态
    - 支持跨服务器消息路由
    - 自动处理服务器故障和连接迁移
    """
    
    def __init__(self):
        self.server_id = self._generate_server_id()
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        self._local_connections: Dict[str, WebSocket] = {}  # 本地连接缓存
        
        # Redis键前缀
        self.CONNECTION_KEY_PREFIX = "ocpp:connection:"
        self.SERVER_KEY_PREFIX = "ocpp:server:"
        self.MESSAGE_QUEUE_PREFIX = "ocpp:message:"
        
        logger.info(f"分布式连接管理器初始化，服务器ID: {self.server_id}")
    
    def _generate_server_id(self) -> str:
        """生成唯一的服务器ID"""
        hostname = socket.gethostname()
        return f"{hostname}-{uuid.uuid4().hex[:8]}"
    
    def connect(self, charger_id: str, websocket: WebSocket):
        """注册连接（本地和Redis）"""
        # 存储本地连接
        self._local_connections[charger_id] = websocket
        
        # 在Redis中注册连接信息
        connection_info = {
            "charger_id": charger_id,
            "server_id": self.server_id,
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
        
        # 设置连接信息（TTL: 1小时，通过心跳续期）
        connection_key = f"{self.CONNECTION_KEY_PREFIX}{charger_id}"
        self.redis_client.setex(
            connection_key,
            3600,  # 1小时TTL
            json.dumps(connection_info)
        )
        
        # 记录服务器处理的充电桩
        server_key = f"{self.SERVER_KEY_PREFIX}{self.server_id}"
        self.redis_client.sadd(server_key, charger_id)
        self.redis_client.expire(server_key, 3600)  # 服务器键也设置TTL
        
        logger.info(f"[{charger_id}] WebSocket连接已注册到服务器 {self.server_id}")
    
    def disconnect(self, charger_id: str):
        """断开连接（清理本地和Redis）"""
        # 清理本地连接
        if charger_id in self._local_connections:
            del self._local_connections[charger_id]
        
        # 清理Redis中的连接信息
        connection_key = f"{self.CONNECTION_KEY_PREFIX}{charger_id}"
        self.redis_client.delete(connection_key)
        
        # 从服务器列表中移除
        server_key = f"{self.SERVER_KEY_PREFIX}{self.server_id}"
        self.redis_client.srem(server_key, charger_id)
        
        logger.info(f"[{charger_id}] WebSocket连接已断开")
    
    def get_local_connection(self, charger_id: str) -> Optional[WebSocket]:
        """获取本地连接"""
        return self._local_connections.get(charger_id)
    
    def is_connected_locally(self, charger_id: str) -> bool:
        """检查是否在本服务器连接"""
        return charger_id in self._local_connections
    
    def is_connected(self, charger_id: str) -> bool:
        """检查充电桩是否在任何服务器连接（查询Redis）"""
        connection_key = f"{self.CONNECTION_KEY_PREFIX}{charger_id}"
        return self.redis_client.exists(connection_key) > 0
    
    def get_connection_server(self, charger_id: str) -> Optional[str]:
        """获取充电桩连接的服务器ID"""
        connection_key = f"{self.CONNECTION_KEY_PREFIX}{charger_id}"
        connection_info = self.redis_client.get(connection_key)
        if connection_info:
            info = json.loads(connection_info)
            return info.get("server_id")
        return None
    
    def update_last_seen(self, charger_id: str):
        """更新最后活跃时间（心跳续期）"""
        connection_key = f"{self.CONNECTION_KEY_PREFIX}{charger_id}"
        connection_info = self.redis_client.get(connection_key)
        
        if connection_info:
            info = json.loads(connection_info)
            info["last_seen"] = datetime.now(timezone.utc).isoformat()
            
            # 更新并续期TTL
            self.redis_client.setex(
                connection_key,
                3600,
                json.dumps(info)
            )
    
    def get_all_connected_chargers(self) -> list:
        """获取所有已连接的充电桩ID（从Redis）"""
        pattern = f"{self.CONNECTION_KEY_PREFIX}*"
        keys = self.redis_client.keys(pattern)
        charger_ids = [key.replace(self.CONNECTION_KEY_PREFIX, "") for key in keys]
        return charger_ids
    
    def get_local_chargers(self) -> list:
        """获取本服务器处理的充电桩ID"""
        return list(self._local_connections.keys())
    
    def count_local(self) -> int:
        """获取本服务器连接数"""
        return len(self._local_connections)
    
    def count_total(self) -> int:
        """获取所有服务器总连接数"""
        return len(self.get_all_connected_chargers())
    
    def publish_message(self, charger_id: str, message: dict):
        """发布消息到Redis Pub/Sub（用于跨服务器通信）"""
        channel = f"{self.MESSAGE_QUEUE_PREFIX}{charger_id}"
        self.redis_client.publish(channel, json.dumps(message))
    
    def subscribe_messages(self, charger_id: str, callback):
        """订阅充电桩的消息（异步处理）"""
        import threading
        channel = f"{self.MESSAGE_QUEUE_PREFIX}{charger_id}"
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe(channel)
        
        def message_handler():
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        callback(charger_id, data)
                    except Exception as e:
                        logger.error(f"处理订阅消息失败: {e}", exc_info=True)
        
        thread = threading.Thread(target=message_handler, daemon=True)
        thread.start()
        return pubsub


# 全局分布式连接管理器实例
distributed_connection_manager = DistributedConnectionManager()

