#
# OCPP 1.6J CSMS 主应用
# 重构后的清晰版本，模块化设计
#

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 核心模块
from app.core.config import get_settings
from app.core.logging_config import setup_logging, get_logger
from app.core.middleware import LoggingMiddleware, SecurityHeadersMiddleware
from app.core.exceptions import (
    OCPPException, http_exception_handler, 
    validation_exception_handler, general_exception_handler
)
from app.database import init_db, check_db_health
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException

# API路由
from app.api.v1 import api_router

# OCPP WebSocket
from app.ocpp.websocket import ocpp_websocket_route

# 设置日志
setup_logging()
logger = get_logger("ocpp_csms")

# 获取配置
settings = get_settings()


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info(f"启动 {settings.app_name} v{settings.app_version}")
    logger.info(f"环境: {settings.environment}")
    
    # 初始化数据库
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}", exc_info=True)
        raise
    
    # 检查数据库连接
    if not check_db_health():
        logger.warning("数据库连接健康检查失败")
    
    # 如果启用分布式模式，启动消息订阅器
    if settings.enable_distributed:
        from app.ocpp.redis_message_subscriber import redis_message_subscriber
        redis_message_subscriber.start()
        logger.info("分布式模式已启用，消息订阅器已启动")
    
    yield
    
    # 关闭时
    if settings.enable_distributed:
        from app.ocpp.redis_message_subscriber import redis_message_subscriber
        redis_message_subscriber.stop()
    logger.info("应用关闭")


# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="OCPP 1.6J 充电站管理系统",
    lifespan=lifespan,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url
)

# 中间件
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# 异常处理器
app.add_exception_handler(OCPPException, http_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 注册API路由
app.include_router(api_router)

# OCPP WebSocket路由
app.websocket("/ocpp")(ocpp_websocket_route)

# 健康检查端点
@app.get("/health", tags=["System"])
def health():
    """基础健康检查"""
    from datetime import datetime, timezone
    return {
        "ok": True,
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health/detailed", tags=["System"])
def health_detailed():
    """详细健康检查"""
    from app.ocpp.connection_manager import connection_manager
    
    db_healthy = check_db_health()
    ws_connections = connection_manager.count()
    
    return {
        "ok": db_healthy,
        "service": settings.app_name,
        "version": settings.app_version,
        "components": {
            "database": {
                "status": "healthy" if db_healthy else "unhealthy",
                "type": "PostgreSQL"
            },
            "websockets": {
                "connections": ws_connections,
                "status": "operational"
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main_new:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )

