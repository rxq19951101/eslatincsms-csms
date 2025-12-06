#
# 订单管理API
# 提供充电订单的查询和管理
#

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db, Order

router = APIRouter()


@router.get("", summary="获取订单列表")
def list_orders(
    user_id: Optional[str] = Query(None, description="用户ID"),
    charger_id: Optional[str] = Query(None, description="充电桩ID"),
    status: Optional[str] = Query(None, description="状态过滤"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> List[dict]:
    """获取订单列表"""
    query = db.query(Order)
    
    if user_id:
        query = query.filter(Order.user_id == user_id)
    if charger_id:
        query = query.filter(Order.charger_id == charger_id)
    if status:
        query = query.filter(Order.status == status)
    
    orders = query.order_by(Order.start_time.desc()).offset(offset).limit(limit).all()
    
    return [
        {
            "id": o.id,
            "charger_id": o.charger_id,
            "user_id": o.user_id,
            "id_tag": o.id_tag,
            "start_time": o.start_time.isoformat() if o.start_time else None,
            "end_time": o.end_time.isoformat() if o.end_time else None,
            "energy_kwh": o.energy_kwh,
            "duration_minutes": o.duration_minutes,
            "total_cost": o.total_cost,
            "status": o.status,
        }
        for o in orders
    ]

