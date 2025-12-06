#
# OCPP 1.6J CSMS 生产版本
# 整合数据库、安全、日志、监控等生产级功能
#

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Query, Body, 
    HTTPException, Depends, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import redis

# 导入配置和工具
from app.config import get_settings
from app.logging_config import setup_logging, get_logger
from app.database import get_db, init_db, check_db_health
from app.exceptions import (
    OCPPException, ChargerNotFoundException, ChargerNotConnectedException,
    http_exception_handler, validation_exception_handler, general_exception_handler
)
from app.middleware import LoggingMiddleware, SecurityHeadersMiddleware
from app.security import verify_charger_id

# 设置日志
setup_logging()
logger = get_logger("ocpp_csms")

# 获取配置
settings = get_settings()

# ---- 生命周期管理 ----
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
    
    yield
    
    # 关闭时
    logger.info("应用关闭")

# ---- 创建FastAPI应用 ----
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="OCPP 1.6J 充电站管理系统 - 生产版本",
    lifespan=lifespan,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url
)

# ---- 中间件 ----
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# ---- 异常处理器 ----
app.add_exception_handler(OCPPException, http_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# ---- Redis客户端 ----
redis_client: redis.Redis = redis.from_url(
    settings.redis_url,
    decode_responses=settings.redis_decode_responses
)

# ---- WebSocket连接注册表 ----
charger_websockets: Dict[str, WebSocket] = {}

# ---- 工具函数 ----
def now_iso() -> str:
    """获取当前ISO格式时间"""
    return datetime.now(timezone.utc).isoformat()


# ---- 健康检查端点 ----
@app.get("/health", tags=["System"])
def health() -> Dict[str, Any]:
    """基础健康检查"""
    return {
        "ok": True,
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": now_iso()
    }


@app.get("/health/detailed", tags=["System"])
def health_detailed() -> Dict[str, Any]:
    """详细健康检查"""
    db_healthy = check_db_health()
    
    try:
        redis_client.ping()
        redis_healthy = True
    except Exception:
        redis_healthy = False
    
    ws_connections = len(charger_websockets)
    
    return {
        "ok": db_healthy and redis_healthy,
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": now_iso(),
        "components": {
            "database": {
                "status": "healthy" if db_healthy else "unhealthy",
                "type": "PostgreSQL"
            },
            "redis": {
                "status": "healthy" if redis_healthy else "unhealthy",
                "type": "Redis"
            },
            "websockets": {
                "connections": ws_connections,
                "status": "operational"
            }
        }
    }


# ---- 导入现有功能 ----
# 注意：这里需要导入main.py中的路由和功能
# 为了简化，我们保留原有结构但添加数据库支持

# TODO: 将原有路由迁移到使用数据库的版本
# 暂时保留原有功能以确保兼容性

# 这是一个示例，展示如何整合
# 实际实现需要将main.py中的功能逐步迁移

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main_production:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )

