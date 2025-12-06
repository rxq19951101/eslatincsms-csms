#
# 数据库基础配置
# 包含数据库引擎、会话工厂等基础组件
#

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.ext.declarative import declarative_base
from app.core.config import get_settings

settings = get_settings()

# 创建Base（在models中会继承）
Base = declarative_base()

# 创建数据库引擎（带连接池）
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # 自动重连
    pool_recycle=settings.db_pool_recycle,   # 1小时后回收连接
    echo=settings.db_echo
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 数据库依赖注入
def get_db() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 初始化数据库
def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)


# 数据库健康检查
def check_db_health() -> bool:
    """检查数据库连接健康状态"""
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False

