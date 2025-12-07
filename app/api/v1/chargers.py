#
# 充电桩管理API
# 提供充电桩的CRUD操作
#

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db, Charger
from app.core.logging_config import get_logger

logger = get_logger("ocpp_csms")

router = APIRouter()


@router.get("", summary="获取所有充电桩")
def list_chargers(
    filter_type: Optional[str] = Query(None, description="筛选类型: configured(已配置), unconfigured(未配置)"),
    db: Session = Depends(get_db)
) -> List[dict]:
    """
    获取充电桩列表
    
    支持筛选：
    - configured: 只返回已配置的充电桩（有位置和价格）
    - unconfigured: 只返回未配置的充电桩（缺少位置或价格）
    """
    query = db.query(Charger).filter(Charger.is_active == True)
    
    # 根据筛选类型过滤
    if filter_type == "configured":
        # 已配置：有位置和价格
        query = query.filter(
            Charger.latitude.isnot(None),
            Charger.longitude.isnot(None),
            Charger.price_per_kwh.isnot(None),
            Charger.price_per_kwh > 0
        )
    elif filter_type == "unconfigured":
        # 未配置：缺少位置或价格
        query = query.filter(
            or_(
                Charger.latitude.is_(None),
                Charger.longitude.is_(None),
                Charger.price_per_kwh.is_(None),
                Charger.price_per_kwh == 0
            )
        )
    
    chargers = query.all()
    
    result = []
    for c in chargers:
        # 判断配置状态
        has_location = c.latitude is not None and c.longitude is not None
        has_pricing = c.price_per_kwh is not None and c.price_per_kwh > 0
        is_configured = has_location and has_pricing
        
        result.append({
            "id": c.id,
            "vendor": c.vendor,
            "model": c.model,
            "status": c.status,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            "location": {
                "latitude": c.latitude,
                "longitude": c.longitude,
                "address": c.address,
            },
            "connector_type": c.connector_type,
            "charging_rate": c.charging_rate,
            "price_per_kwh": c.price_per_kwh,
            "is_configured": is_configured,
            "has_location": has_location,
            "has_pricing": has_pricing,
        })
    
    return result


@router.get("/{charger_id}", summary="获取充电桩详情")
def get_charger(charger_id: str, db: Session = Depends(get_db)) -> dict:
    """获取单个充电桩的详细信息"""
    charger = db.query(Charger).filter(Charger.id == charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {charger_id} 未找到")
    
    return {
        "id": charger.id,
        "vendor": charger.vendor,
        "model": charger.model,
        "serial_number": charger.serial_number,
        "firmware_version": charger.firmware_version,
        "status": charger.status,
        "last_seen": charger.last_seen.isoformat() if charger.last_seen else None,
        "location": {
            "latitude": charger.latitude,
            "longitude": charger.longitude,
            "address": charger.address,
        },
        "connector_type": charger.connector_type,
        "charging_rate": charger.charging_rate,
        "price_per_kwh": charger.price_per_kwh,
        "created_at": charger.created_at.isoformat() if charger.created_at else None,
        "updated_at": charger.updated_at.isoformat() if charger.updated_at else None,
    }

