#
# Redis消息订阅器
# 监听跨服务器消息路由
#

import json
import asyncio
import threading
from typing import Callable
import redis
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.ocpp.message_router import MessageRouter

logger = get_logger("ocpp_csms")

settings = get_settings()


class RedisMessageSubscriber:
    """Redis消息订阅器
    
    监听来自其他服务器的消息路由请求
    """
    
    def __init__(self):
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        self.pubsub = None
        self.running = False
        self._subscribed_chargers = set()
    
    def start(self):
        """启动消息订阅"""
        if self.running:
            return
        
        self.running = True
        self.pubsub = self.redis_client.pubsub()
        
        # 订阅所有路由通道
        self.pubsub.psubscribe("ocpp:route:*")
        
        # 启动后台线程处理消息
        thread = threading.Thread(target=self._message_loop, daemon=True)
        thread.start()
        
        logger.info("Redis消息订阅器已启动")
    
    def stop(self):
        """停止消息订阅"""
        self.running = False
        if self.pubsub:
            self.pubsub.close()
        logger.info("Redis消息订阅器已停止")
    
    def _message_loop(self):
        """消息处理循环"""
        try:
            for message in self.pubsub.listen():
                if not self.running:
                    break
                
                if message['type'] == 'pmessage':
                    channel = message['channel']
                    data = message['data']
                    
                    try:
                        # 解析充电桩ID
                        charger_id = channel.replace("ocpp:route:", "")
                        
                        # 解析消息
                        message_data = json.loads(data)
                        
                        # 检查是否是本服务器处理的充电桩
                        from app.ocpp.distributed_connection_manager import distributed_connection_manager
                        if distributed_connection_manager.is_connected_locally(charger_id):
                            # 处理路由消息
                            logger.info(f"收到跨服务器消息路由: charger={charger_id}, action={message_data.get('action')}")
                            MessageRouter.handle_routed_message(charger_id, message_data)
                    
                    except Exception as e:
                        logger.error(f"处理订阅消息失败: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"消息订阅循环错误: {e}", exc_info=True)
            self.running = False


# 全局消息订阅器实例
redis_message_subscriber = RedisMessageSubscriber()

