#
# 统计API
# 提供充电桩历史数据统计和监控
#

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case
from app.database import get_db, Charger, Transaction, MeterValue, HeartbeatHistory, StatusHistory
from app.core.logging_config import get_logger

logger = get_logger("ocpp_csms")
router = APIRouter()


@router.get("/charger/{charger_id}/history", summary="获取充电桩历史监控数据")
def get_charger_history(
    charger_id: str,
    days: int = Query(10, ge=1, le=30, description="查询天数，默认10天"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    获取充电桩过去N天的监控数据
    
    返回数据包括：
    - 每日状态变化统计
    - 每日充电次数
    - 每日充电量（kWh）
    - 每日充电时长（分钟）
    - 每日收入（COP）
    - 状态分布
    """
    # 验证充电桩是否存在
    charger = db.query(Charger).filter(Charger.id == charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {charger_id} 未找到")
    
    # 计算时间范围
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # 获取该充电桩的所有事务（已完成）
    transactions = db.query(Transaction).filter(
        Transaction.charger_id == charger_id,
        Transaction.start_time >= start_date,
        Transaction.status == "completed"
    ).all()
    
    # 按天统计数据
    daily_stats = {}
    
    # 初始化所有天的数据
    for i in range(days):
        date = (end_date - timedelta(days=i)).date()
        daily_stats[date.isoformat()] = {
            "date": date.isoformat(),
            "charging_sessions": 0,
            "total_energy_kwh": 0.0,
            "total_duration_minutes": 0.0,
            "total_revenue": 0.0,
            "avg_energy_per_session": 0.0,
            "avg_duration_per_session": 0.0,
        }
    
    # 统计事务数据
    for tx in transactions:
        if tx.start_time:
            tx_date = tx.start_time.date()
            date_key = tx_date.isoformat()
            
            if date_key in daily_stats:
                daily_stats[date_key]["charging_sessions"] += 1
                if tx.energy_kwh:
                    daily_stats[date_key]["total_energy_kwh"] += tx.energy_kwh
                if tx.duration_minutes:
                    daily_stats[date_key]["total_duration_minutes"] += tx.duration_minutes
                if tx.total_cost:
                    daily_stats[date_key]["total_revenue"] += tx.total_cost
    
    # 计算平均值
    for date_key, stats in daily_stats.items():
        if stats["charging_sessions"] > 0:
            stats["avg_energy_per_session"] = stats["total_energy_kwh"] / stats["charging_sessions"]
            stats["avg_duration_per_session"] = stats["total_duration_minutes"] / stats["charging_sessions"]
    
    # 转换为列表并按日期排序
    daily_stats_list = sorted(
        [stats for stats in daily_stats.values()],
        key=lambda x: x["date"]
    )
    
    # 计算总计
    total_stats = {
        "total_sessions": sum(s["charging_sessions"] for s in daily_stats_list),
        "total_energy_kwh": sum(s["total_energy_kwh"] for s in daily_stats_list),
        "total_duration_minutes": sum(s["total_duration_minutes"] for s in daily_stats_list),
        "total_revenue": sum(s["total_revenue"] for s in daily_stats_list),
    }
    
    if total_stats["total_sessions"] > 0:
        total_stats["avg_energy_per_session"] = total_stats["total_energy_kwh"] / total_stats["total_sessions"]
        total_stats["avg_duration_per_session"] = total_stats["total_duration_minutes"] / total_stats["total_sessions"]
    else:
        total_stats["avg_energy_per_session"] = 0.0
        total_stats["avg_duration_per_session"] = 0.0
    
    return {
        "charger_id": charger_id,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "daily_stats": daily_stats_list,
        "total_stats": total_stats,
        "charger_info": {
            "id": charger.id,
            "vendor": charger.vendor,
            "model": charger.model,
            "status": charger.status,
            "location": {
                "latitude": charger.latitude,
                "longitude": charger.longitude,
                "address": charger.address
            },
            "price_per_kwh": charger.price_per_kwh,
            "charging_rate": charger.charging_rate
        }
    }


@router.get("/charger/{charger_id}/status-history", summary="获取充电桩状态变化历史")
def get_charger_status_history(
    charger_id: str,
    days: int = Query(10, ge=1, le=30, description="查询天数"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    获取充电桩状态变化历史
    
    注意：当前实现基于事务数据推断状态，未来可以添加状态历史表
    """
    charger = db.query(Charger).filter(Charger.id == charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {charger_id} 未找到")
    
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # 获取该时间段内的所有事务
    transactions = db.query(Transaction).filter(
        Transaction.charger_id == charger_id,
        Transaction.start_time >= start_date
    ).all()
    
    # 按天统计状态分布（基于事务推断）
    daily_status = {}
    
    for i in range(days):
        date = (end_date - timedelta(days=i)).date()
        daily_status[date.isoformat()] = {
            "date": date.isoformat(),
            "status_distribution": {
                "Available": 0,
                "Charging": 0,
                "Offline": 0,
                "Faulted": 0,
                "Unavailable": 0
            }
        }
    
    # 统计每天的状态（基于事务）
    for tx in transactions:
        if tx.start_time:
            tx_date = tx.start_time.date()
            date_key = tx_date.isoformat()
            
            if date_key in daily_status:
                # 有事务表示当天有充电，推断为Charging状态
                daily_status[date_key]["status_distribution"]["Charging"] += 1
    
    # 转换为列表
    status_history = sorted(
        [stats for stats in daily_status.values()],
        key=lambda x: x["date"]
    )
    
    return {
        "charger_id": charger_id,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "status_history": status_history
    }


@router.get("/charger/{charger_id}/heartbeat-history", summary="获取充电桩心跳历史")
def get_charger_heartbeat_history(
    charger_id: str,
    hours: int = Query(24, ge=1, le=168, description="查询小时数，默认24小时"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    获取充电桩心跳历史数据，用于健康状态监控
    
    返回数据包括：
    - 心跳时间点列表
    - 每个心跳点的健康状态（normal/warning/abnormal）
    - 心跳间隔统计
    """
    charger = db.query(Charger).filter(Charger.id == charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {charger_id} 未找到")
    
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    # 获取心跳历史记录
    heartbeats = db.query(HeartbeatHistory).filter(
        HeartbeatHistory.charger_id == charger_id,
        HeartbeatHistory.timestamp >= start_time,
        HeartbeatHistory.timestamp <= end_time
    ).order_by(HeartbeatHistory.timestamp.asc()).all()
    
    # 转换为前端需要的格式
    heartbeat_data = []
    for hb in heartbeats:
        heartbeat_data.append({
            "timestamp": hb.timestamp.isoformat(),
            "health_status": hb.health_status,
            "interval_seconds": hb.interval_seconds,
        })
    
    # 统计健康状态分布
    health_stats = {
        "normal": len([h for h in heartbeat_data if h["health_status"] == "normal"]),
        "warning": len([h for h in heartbeat_data if h["health_status"] == "warning"]),
        "abnormal": len([h for h in heartbeat_data if h["health_status"] == "abnormal"]),
    }
    
    # 计算平均心跳间隔
    intervals = [h["interval_seconds"] for h in heartbeat_data if h["interval_seconds"] is not None]
    avg_interval = sum(intervals) / len(intervals) if intervals else None
    
    return {
        "charger_id": charger_id,
        "period": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "hours": hours
        },
        "heartbeats": heartbeat_data,
        "health_stats": health_stats,
        "avg_interval_seconds": avg_interval,
        "total_heartbeats": len(heartbeat_data)
    }


@router.get("/charger/{charger_id}/status-timeline", summary="获取充电桩状态时间线")
def get_charger_status_timeline(
    charger_id: str,
    hours: int = Query(24, ge=1, le=168, description="查询小时数，默认24小时"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    获取充电桩状态变化时间线
    
    返回数据包括：
    - 状态变化记录
    - 每个状态的持续时间
    - 状态分布统计（离线、空闲、充电中）
    """
    charger = db.query(Charger).filter(Charger.id == charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {charger_id} 未找到")
    
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    # 获取状态历史记录
    status_records = db.query(StatusHistory).filter(
        StatusHistory.charger_id == charger_id,
        StatusHistory.timestamp >= start_time,
        StatusHistory.timestamp <= end_time
    ).order_by(StatusHistory.timestamp.asc()).all()
    
    # 转换为前端需要的格式
    timeline_data = []
    for record in status_records:
        timeline_data.append({
            "timestamp": record.timestamp.isoformat(),
            "status": record.status,
            "previous_status": record.previous_status,
            "duration_seconds": record.duration_seconds,
        })
    
    # 统计状态分布（按小时分组）
    # 将时间线按小时分组，统计每个小时的状态分布
    hourly_status = {}
    current_status = charger.status  # 当前状态
    
    # 从最新到最旧遍历，构建每小时的状态
    for i in range(hours):
        hour_start = end_time - timedelta(hours=i+1)
        hour_end = end_time - timedelta(hours=i)
        
        # 找到这个小时内的状态变化
        hour_statuses = [r for r in status_records if hour_start <= r.timestamp < hour_end]
        
        # 统计这个小时内的状态分布
        status_counts = {
            "Offline": 0,
            "Available": 0,
            "Charging": 0,
            "Faulted": 0,
            "Unavailable": 0
        }
        
        # 如果有状态变化，使用变化后的状态
        if hour_statuses:
            # 使用最后一个状态变化后的状态
            last_status = hour_statuses[-1].status
            status_counts[last_status] = 1
        else:
            # 如果没有状态变化，使用当前状态
            if current_status in status_counts:
                status_counts[current_status] = 1
        
        hour_key = hour_end.strftime("%Y-%m-%d %H:00")
        hourly_status[hour_key] = status_counts
    
    # 转换为列表格式
    hourly_status_list = [
        {
            "hour": hour,
            "status_distribution": status_dist
        }
        for hour, status_dist in sorted(hourly_status.items())
    ]
    
    # 总体状态分布统计
    total_status_dist = {
        "Offline": 0,
        "Available": 0,
        "Charging": 0,
        "Faulted": 0,
        "Unavailable": 0
    }
    
    for record in status_records:
        if record.status in total_status_dist:
            total_status_dist[record.status] += 1
    
    return {
        "charger_id": charger_id,
        "period": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "hours": hours
        },
        "timeline": timeline_data,
        "hourly_status": hourly_status_list,
        "total_status_distribution": total_status_dist,
        "current_status": charger.status
    }

