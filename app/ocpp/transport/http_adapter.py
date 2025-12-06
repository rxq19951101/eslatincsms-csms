#
# HTTP 传输适配器
# 支持 OCPP 消息通过 HTTP POST 传输
#

import json
import logging
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException
from .base import TransportAdapter, TransportType

logger = logging.getLogger("ocpp_csms")


class HTTPAdapter(TransportAdapter):
    """HTTP 传输适配器
    
    支持 OCPP 消息通过 HTTP POST 传输
    端点格式: POST /ocpp/{charger_id}
    """
    
    def __init__(self):
        super().__init__(TransportType.HTTP)
        self._charger_sessions: Dict[str, Dict[str, Any]] = {}
        self._pending_requests: Dict[str, Dict[str, Any]] = {}
    
    async def start(self) -> None:
        """启动 HTTP 服务（由 FastAPI 管理，这里只做初始化）"""
        logger.info("HTTP 传输适配器已初始化")
    
    async def stop(self) -> None:
        """停止 HTTP 服务"""
        self._charger_sessions.clear()
        self._pending_requests.clear()
        logger.info("HTTP 传输适配器已停止")
    
    async def send_message(
        self,
        charger_id: str,
        action: str,
        payload: Dict[str, Any],
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """发送消息到充电桩（HTTP 模式下需要充电桩主动轮询）"""
        # HTTP 是请求-响应模式，CSMS 无法主动推送
        # 需要将消息存储，等待充电桩轮询获取
        request_id = f"{charger_id}_{action}_{id(payload)}"
        
        # 存储待发送的消息
        if charger_id not in self._pending_requests:
            self._pending_requests[charger_id] = {}
        
        self._pending_requests[charger_id][request_id] = {
            "action": action,
            "payload": payload,
            "timestamp": None,
        }
        
        logger.info(f"[{charger_id}] HTTP 消息已排队: {action}")
        
        # 返回排队确认
        return {
            "success": True,
            "message": "Message queued, waiting for charger to poll",
            "request_id": request_id
        }
    
    def is_connected(self, charger_id: str) -> bool:
        """检查充电桩是否已连接（HTTP 模式下基于最近请求时间）"""
        if charger_id in self._charger_sessions:
            # 检查会话是否过期（例如 5 分钟内没有请求）
            session = self._charger_sessions[charger_id]
            # 这里可以添加时间检查逻辑
            return True
        return False
    
    async def handle_http_request(
        self,
        charger_id: str,
        request: Request
    ) -> Dict[str, Any]:
        """处理 HTTP 请求
        
        充电桩通过 POST 发送 OCPP 消息
        同时可以 GET 获取待处理的 CSMS 消息
        """
        if request.method == "POST":
            # 充电桩发送消息
            try:
                body = await request.json()
                action = body.get("action", "")
                payload = body.get("payload", {})
                
                logger.info(f"[{charger_id}] <- HTTP OCPP {action}")
                
                # 更新会话
                self._charger_sessions[charger_id] = {
                    "last_seen": None,  # 可以添加时间戳
                    "transport": "http"
                }
                
                # 处理消息
                response = await self.handle_incoming_message(charger_id, action, payload)
                
                # 检查是否有待发送的消息
                pending = self._get_pending_message(charger_id)
                
                return {
                    "response": response,
                    "pending": pending
                }
                
            except Exception as e:
                logger.error(f"[{charger_id}] HTTP 请求处理错误: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))
        
        elif request.method == "GET":
            # 充电桩轮询获取待处理消息
            pending = self._get_pending_message(charger_id)
            return {"pending": pending}
        
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")
    
    def _get_pending_message(self, charger_id: str) -> Optional[Dict[str, Any]]:
        """获取待发送的消息"""
        if charger_id in self._pending_requests:
            requests = self._pending_requests[charger_id]
            if requests:
                # 返回第一个待处理的消息
                request_id, message = next(iter(requests.items()))
                del requests[request_id]
                return {
                    "action": message["action"],
                    "payload": message["payload"]
                }
        return None

