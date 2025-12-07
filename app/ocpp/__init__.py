#
# OCPP协议处理模块
# 包含OCPP消息处理、WebSocket管理、消息验证等
#

# 延迟导入，避免循环依赖
try:
    from app.ocpp.connection_manager import ConnectionManager
except ImportError:
    ConnectionManager = None

try:
    from app.ocpp.handlers import OCPPHandler
except ImportError:
    OCPPHandler = None

try:
    from app.ocpp.websocket import ocpp_websocket_route
except ImportError:
    ocpp_websocket_route = None

__all__ = [
    "ConnectionManager",
    "OCPPHandler",
    "ocpp_websocket_route",
]

