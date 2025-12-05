#
# OCPP WebSocket路由
# 处理WebSocket连接和消息路由
#

import json
from fastapi import WebSocket, WebSocketDisconnect, Query, HTTPException
from app.ocpp.handlers import OCPPHandler
from app.database import get_db
from app.core.logging_config import get_logger
from app.core.config import get_settings

settings = get_settings()

# 根据配置选择使用分布式或单机连接管理器
if settings.enable_distributed:
    from app.ocpp.distributed_connection_manager import distributed_connection_manager as connection_manager
else:
    from app.ocpp.connection_manager import connection_manager

logger = get_logger("ocpp_csms")


async def ocpp_websocket_route(websocket: WebSocket, id: str = Query(..., description="Charger ID")):
    """
    OCPP WebSocket路由
    处理充电桩的WebSocket连接
    """
    # 强制OCPP 1.6子协议协商
    requested_proto = (websocket.headers.get("sec-websocket-protocol") or "").strip()
    requested = [p.strip() for p in requested_proto.split(",") if p.strip()]
    if "ocpp1.6" not in requested:
        await websocket.close(code=1002)
        return
    
    await websocket.accept(subprotocol="ocpp1.6")
    
    # 注册连接
    connection_manager.connect(id, websocket)
    logger.info(f"[{id}] WebSocket连接已建立，子协议=ocpp1.6")
    
    # 获取数据库会话
    db = next(get_db())
    
    try:
        # 初始化充电桩记录
        handler = OCPPHandler(db)
        
        # 发送连接确认
        await websocket.send_text(json.dumps({"result": "Connected", "id": id}))
        
        # 定期更新心跳（分布式模式）
        if settings.enable_distributed:
            import asyncio
            async def heartbeat_updater():
                while True:
                    await asyncio.sleep(30)  # 每30秒更新一次
                    connection_manager.update_last_seen(id)
            
            heartbeat_task = asyncio.create_task(heartbeat_updater())
        
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
                continue
            
            action = str(msg.get("action", "")).strip()
            payload = msg.get("payload", {})
            
            logger.info(f"[{id}] <- OCPP {action} | payload={json.dumps(payload)}")
            
            try:
                # 处理消息
                response = await handler.handle_message(id, action, payload)
                
                logger.info(f"[{id}] -> OCPP响应: {action}")
                await websocket.send_text(json.dumps(response))
                
            except ValueError as e:
                logger.error(f"[{id}] 未知的OCPP动作: {action}")
                await websocket.send_text(json.dumps({"error": "UnknownAction", "action": action}))
            except Exception as e:
                logger.error(f"[{id}] 处理消息失败: {e}", exc_info=True)
                await websocket.send_text(json.dumps({
                    "error": "InternalError", 
                    "detail": str(e)
                }))
    
    except WebSocketDisconnect:
        logger.info(f"[{id}] WebSocket断开连接")
    except Exception as e:
        logger.error(f"[{id}] WebSocket错误: {e}", exc_info=True)
    finally:
        # 停止心跳任务
        if settings.enable_distributed and 'heartbeat_task' in locals():
            heartbeat_task.cancel()
        # 断开连接
        connection_manager.disconnect(id)
        logger.info(f"[{id}] WebSocket已注销")

