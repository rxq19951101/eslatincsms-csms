#
# 数据库模块
# 包含数据模型、数据库连接、仓储模式等
#

# 先导入models以定义Base
from app.database.models import (
    Base, Charger, Transaction, MeterValue, 
    ChargerConfiguration, Order, SupportMessage, OCPPErrorLog,
    HeartbeatHistory, StatusHistory
)

# 然后导入base（需要Base已定义）
from app.database.base import engine, SessionLocal, get_db, init_db, check_db_health
from sqlalchemy.orm import Session

__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "Session",  # SQLAlchemy Session 类型
    "get_db",
    "init_db",
    "check_db_health",
    "Charger",
    "Transaction",
    "MeterValue",
    "ChargerConfiguration",
    "Order",
    "SupportMessage",
    "OCPPErrorLog",
    "HeartbeatHistory",
    "StatusHistory",
]
