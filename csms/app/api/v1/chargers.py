#
# 充电桩管理API
# 提供充电桩的CRUD操作
#

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db, Charger
from app.core.logging_config import get_logger

logger = get_logger("ocpp_csms")

router = APIRouter()


@router.get("", summary="获取所有充电桩")
def list_chargers(db: Session = Depends(get_db)) -> List[dict]:
    """获取所有充电桩列表"""
    chargers = db.query(Charger).filter(Charger.is_active == True).all()
    return [
        {
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
        }
        for c in chargers
    ]


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

