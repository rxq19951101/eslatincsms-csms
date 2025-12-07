#
# 数据库模型
# 定义所有数据表结构
#

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, 
    DateTime, Text, ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship
from app.database.base import Base


class Charger(Base):
    """充电桩基本信息"""
    __tablename__ = "chargers"
    
    id = Column(String(100), primary_key=True, index=True)
    vendor = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    serial_number = Column(String(100), nullable=True)
    firmware_version = Column(String(50), nullable=True)
    
    # 位置信息
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    address = Column(Text, nullable=True)
    
    # 配置信息
    connector_type = Column(String(50), default="Type2")
    charging_rate = Column(Float, default=7.0)  # kW
    price_per_kwh = Column(Float, default=2700.0)  # COP/kWh
    
    # 状态信息
    status = Column(String(50), default="Unknown")
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # 元数据
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    
    # 关系
    transactions = relationship("Transaction", back_populates="charger", cascade="all, delete-orphan")
    configurations = relationship("ChargerConfiguration", back_populates="charger", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_chargers_status', 'status'),
        Index('idx_chargers_last_seen', 'last_seen'),
    )


class Transaction(Base):
    """充电事务"""
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    charger_id = Column(String(100), ForeignKey("chargers.id"), nullable=False, index=True)
    transaction_id = Column(Integer, nullable=False, index=True)
    
    # 用户信息
    id_tag = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=True)
    
    # 时间信息
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    
    # 计量信息
    meter_start = Column(Integer, default=0)
    meter_stop = Column(Integer, nullable=True)
    energy_kwh = Column(Float, nullable=True)
    duration_minutes = Column(Float, nullable=True)
    
    # 费率信息
    charging_rate = Column(Float, nullable=True)
    price_per_kwh = Column(Float, nullable=True)
    total_cost = Column(Float, nullable=True)
    
    # 状态
    status = Column(String(50), default="ongoing")  # ongoing, completed, cancelled
    
    # 元数据
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # 关系
    charger = relationship("Charger", back_populates="transactions")
    meter_values = relationship("MeterValue", back_populates="transaction", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_transactions_status', 'status'),
        Index('idx_transactions_id_tag', 'id_tag'),
        Index('idx_transactions_start_time', 'start_time'),
    )


class MeterValue(Base):
    """计量值记录"""
    __tablename__ = "meter_values"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    
    connector_id = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # 计量数据（JSON格式存储完整数据）
    value = Column(Integer, nullable=False)  # 主要值（Wh）
    sampled_value = Column(JSON, nullable=True)  # 完整采样值数据
    
    # 关系
    transaction = relationship("Transaction", back_populates="meter_values")
    
    __table_args__ = (
        Index('idx_meter_values_timestamp', 'timestamp'),
    )


class ChargerConfiguration(Base):
    """充电桩配置参数"""
    __tablename__ = "charger_configurations"
    
    id = Column(Integer, primary_key=True, index=True)
    charger_id = Column(String(100), ForeignKey("chargers.id"), nullable=False, index=True)
    
    config_key = Column(String(100), nullable=False)
    config_value = Column(Text, nullable=True)
    
    # 元数据
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # 关系
    charger = relationship("Charger", back_populates="configurations")
    
    __table_args__ = (
        Index('idx_config_charger_key', 'charger_id', 'config_key', unique=True),
    )


class Order(Base):
    """充电订单（业务层）"""
    __tablename__ = "orders"
    
    id = Column(String(100), primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)
    charger_id = Column(String(100), ForeignKey("chargers.id"), nullable=False, index=True)
    
    user_id = Column(String(100), nullable=False, index=True)
    id_tag = Column(String(100), nullable=False)
    
    # 时间信息
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    
    # 计量和费用
    energy_kwh = Column(Float, nullable=True)
    duration_minutes = Column(Float, nullable=True)
    charging_rate = Column(Float, nullable=True)
    price_per_kwh = Column(Float, nullable=True)
    total_cost = Column(Float, nullable=True)
    
    # 状态
    status = Column(String(50), default="ongoing")  # ongoing, completed, cancelled
    
    # 元数据
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_orders_status', 'status'),
        Index('idx_orders_user_id', 'user_id'),
        Index('idx_orders_start_time', 'start_time'),
    )


class SupportMessage(Base):
    """客服消息"""
    __tablename__ = "support_messages"
    
    id = Column(String(100), primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    username = Column(String(100), nullable=False)
    
    message = Column(Text, nullable=False)
    reply = Column(Text, nullable=True)
    
    status = Column(String(50), default="pending")  # pending, replied
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    replied_at = Column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        Index('idx_messages_status', 'status'),
        Index('idx_messages_user_id', 'user_id'),
        Index('idx_messages_created_at', 'created_at'),
    )


class OCPPErrorLog(Base):
    """OCPP错误日志"""
    __tablename__ = "ocpp_error_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    charger_id = Column(String(100), nullable=True, index=True)
    
    action = Column(String(100), nullable=False)
    error_code = Column(String(100), nullable=False)
    error_description = Column(Text, nullable=True)
    
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    __table_args__ = (
        Index('idx_error_logs_timestamp', 'timestamp'),
        Index('idx_error_logs_charger_id', 'charger_id'),
    )


class HeartbeatHistory(Base):
    """心跳历史记录"""
    __tablename__ = "heartbeat_history"
    
    id = Column(Integer, primary_key=True, index=True)
    charger_id = Column(String(100), nullable=False, index=True)
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # 健康状态：基于心跳间隔计算
    # 正常：心跳间隔 <= 35秒
    # 警告：心跳间隔 35-60秒
    # 异常：心跳间隔 > 60秒或丢失
    health_status = Column(String(20), default="normal")  # normal, warning, abnormal
    
    # 心跳间隔（秒）
    interval_seconds = Column(Float, nullable=True)
    
    __table_args__ = (
        Index('idx_heartbeat_charger_timestamp', 'charger_id', 'timestamp'),
        Index('idx_heartbeat_timestamp', 'timestamp'),
    )


class StatusHistory(Base):
    """状态变化历史记录"""
    __tablename__ = "status_history"
    
    id = Column(Integer, primary_key=True, index=True)
    charger_id = Column(String(100), nullable=False, index=True)
    
    status = Column(String(50), nullable=False)  # Available, Charging, Offline, Faulted, Unavailable
    previous_status = Column(String(50), nullable=True)
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # 状态持续时间（秒），用于统计
    duration_seconds = Column(Float, nullable=True)
    
    __table_args__ = (
        Index('idx_status_charger_timestamp', 'charger_id', 'timestamp'),
        Index('idx_status_timestamp', 'timestamp'),
        Index('idx_status_charger_status', 'charger_id', 'status'),
    )
