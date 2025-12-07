#
# 历史记录工具
# 用于记录充电桩心跳和状态变化历史到数据库
#

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal, HeartbeatHistory, StatusHistory, Charger
from app.core.logging_config import get_logger

logger = get_logger("ocpp_csms")


def record_heartbeat(charger_id: str, previous_heartbeat_time: Optional[datetime] = None) -> None:
    """
    记录心跳历史
    
    Args:
        charger_id: 充电桩ID
        previous_heartbeat_time: 上一次心跳时间，用于计算间隔
    """
    try:
        db: Session = SessionLocal()
        try:
            current_time = datetime.now(timezone.utc)
            
            # 计算心跳间隔
            interval_seconds = None
            health_status = "normal"
            
            if previous_heartbeat_time:
                interval_seconds = (current_time - previous_heartbeat_time).total_seconds()
                # 判断健康状态
                if interval_seconds <= 35:
                    health_status = "normal"
                elif interval_seconds <= 60:
                    health_status = "warning"
                else:
                    health_status = "abnormal"
            
            # 创建心跳记录
            heartbeat = HeartbeatHistory(
                charger_id=charger_id,
                timestamp=current_time,
                health_status=health_status,
                interval_seconds=interval_seconds
            )
            
            db.add(heartbeat)
            db.commit()
            
            logger.debug(f"[{charger_id}] 心跳记录已保存: {health_status}, 间隔: {interval_seconds}s")
        except Exception as e:
            db.rollback()
            logger.error(f"[{charger_id}] 记录心跳历史失败: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[{charger_id}] 创建数据库会话失败: {e}", exc_info=True)


def record_status_change(charger_id: str, new_status: str, previous_status: Optional[str] = None) -> None:
    """
    记录状态变化历史
    
    Args:
        charger_id: 充电桩ID
        new_status: 新状态
        previous_status: 之前的状态
    """
    try:
        db: Session = SessionLocal()
        try:
            current_time = datetime.now(timezone.utc)
            
            # 计算上一个状态的持续时间
            duration_seconds = None
            if previous_status:
                # 查找上一个状态记录
                last_status_record = db.query(StatusHistory).filter(
                    StatusHistory.charger_id == charger_id
                ).order_by(StatusHistory.timestamp.desc()).first()
                
                if last_status_record:
                    duration_seconds = (current_time - last_status_record.timestamp).total_seconds()
            
            # 创建状态记录
            status_record = StatusHistory(
                charger_id=charger_id,
                status=new_status,
                previous_status=previous_status,
                timestamp=current_time,
                duration_seconds=duration_seconds
            )
            
            db.add(status_record)
            db.commit()
            
            logger.debug(f"[{charger_id}] 状态变化已记录: {previous_status} -> {new_status}")
        except Exception as e:
            db.rollback()
            logger.error(f"[{charger_id}] 记录状态历史失败: {e}", exc_info=True)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[{charger_id}] 创建数据库会话失败: {e}", exc_info=True)


def get_last_heartbeat_time(charger_id: str) -> Optional[datetime]:
    """
    获取最后一次心跳时间
    
    Args:
        charger_id: 充电桩ID
        
    Returns:
        最后一次心跳时间，如果没有则返回None
    """
    try:
        db: Session = SessionLocal()
        try:
            last_heartbeat = db.query(HeartbeatHistory).filter(
                HeartbeatHistory.charger_id == charger_id
            ).order_by(HeartbeatHistory.timestamp.desc()).first()
            
            if last_heartbeat:
                return last_heartbeat.timestamp
            return None
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[{charger_id}] 获取最后心跳时间失败: {e}", exc_info=True)
        return None


def get_last_status(charger_id: str) -> Optional[str]:
    """
    获取充电桩的最后一个状态
    
    Args:
        charger_id: 充电桩ID
        
    Returns:
        最后一个状态，如果没有则返回None
    """
    try:
        db: Session = SessionLocal()
        try:
            charger = db.query(Charger).filter(Charger.id == charger_id).first()
            if charger:
                return charger.status
            return None
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[{charger_id}] 获取最后状态失败: {e}", exc_info=True)
        return None

