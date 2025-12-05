#
# 多传输方式集成示例
# 展示如何在 main.py 中集成 WebSocket、HTTP 和 MQTT
#

"""
在 main.py 中添加以下代码以支持多种传输方式：

1. 导入必要的模块
2. 初始化传输管理器
3. 添加 HTTP 端点
4. 集成到现有的 WebSocket 处理
5. 更新 send_ocpp_call 函数使用传输管理器
"""

# 示例代码片段（需要集成到 main.py）：

"""
# 1. 在文件顶部添加导入
from app.ocpp.transport_manager import transport_manager, TransportType
from app.ocpp.transport import HTTPAdapter, MQTTAdapter
from contextlib import asynccontextmanager

# 2. 创建统一的 OCPP 消息处理函数
async def handle_ocpp_message(charger_id: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    \"\"\"统一的 OCPP 消息处理函数，所有传输方式都使用这个函数\"\"\"
    charger = next((c for c in load_chargers() if c["id"] == charger_id), get_default_charger(charger_id))
    charger["last_seen"] = now_iso()
    
    # 这里可以复用现有的消息处理逻辑
    # 例如 BootNotification、Heartbeat 等的处理
    # ... 现有的处理逻辑 ...
    
    # 返回响应
    return response

# 3. 在应用启动时初始化传输管理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    enabled_transports = [TransportType.WEBSOCKET]
    
    # 根据配置启用 HTTP
    from app.core.config import get_settings
    settings = get_settings()
    if settings.enable_http_transport:
        enabled_transports.append(TransportType.HTTP)
    
    # 根据配置启用 MQTT
    if settings.enable_mqtt_transport:
        enabled_transports.append(TransportType.MQTT)
    
    # 初始化传输管理器
    await transport_manager.initialize(enabled_transports)
    
    # 设置消息处理器
    transport_manager.set_message_handler(handle_ocpp_message)
    
    yield
    
    # 关闭时
    await transport_manager.shutdown()

# 4. 更新 FastAPI 应用使用 lifespan
app = FastAPI(
    title="OCPP 1.6J CSMS - Multi-Transport",
    lifespan=lifespan
)

# 5. 添加 HTTP 端点
@app.post("/ocpp/{charger_id}")
async def ocpp_http(charger_id: str, request: Request):
    \"\"\"HTTP OCPP 端点\"\"\"
    http_adapter = transport_manager.get_adapter(TransportType.HTTP)
    if not http_adapter:
        raise HTTPException(status_code=503, detail="HTTP transport not enabled")
    
    return await http_adapter.handle_http_request(charger_id, request)

# 6. 更新 WebSocket 端点以使用传输管理器
@app.websocket("/ocpp")
async def ocpp_ws(ws: WebSocket, id: str = Query(..., description="Charger ID")):
    # ... 现有的 WebSocket 处理逻辑 ...
    # 但使用传输管理器注册连接
    ws_adapter = transport_manager.get_adapter(TransportType.WEBSOCKET)
    if ws_adapter:
        await ws_adapter.register_connection(id, ws)
    
    # ... 其余处理逻辑 ...

# 7. 更新 send_ocpp_call 函数使用传输管理器
async def send_ocpp_call(charger_id: str, action: str, payload: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    \"\"\"使用传输管理器发送 OCPP 消息\"\"\"
    try:
        return await transport_manager.send_message(charger_id, action, payload, timeout=timeout)
    except Exception as e:
        logger.error(f"[{charger_id}] 发送 OCPP 消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send OCPP call: {str(e)}")
"""

