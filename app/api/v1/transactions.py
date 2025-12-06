#
# 事务管理API
# 提供充电事务的查询和管理
#

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db, Transaction

router = APIRouter()


@router.get("", summary="获取事务列表")
def list_transactions(
    charger_id: Optional[str] = Query(None, description="充电桩ID"),
    status: Optional[str] = Query(None, description="状态过滤"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> List[dict]:
    """获取事务列表"""
    query = db.query(Transaction)
    
    if charger_id:
        query = query.filter(Transaction.charger_id == charger_id)
    if status:
        query = query.filter(Transaction.status == status)
    
    transactions = query.order_by(Transaction.start_time.desc()).offset(offset).limit(limit).all()
    
    return [
        {
            "id": t.id,
            "transaction_id": t.transaction_id,
            "charger_id": t.charger_id,
            "id_tag": t.id_tag,
            "user_id": t.user_id,
            "start_time": t.start_time.isoformat() if t.start_time else None,
            "end_time": t.end_time.isoformat() if t.end_time else None,
            "energy_kwh": t.energy_kwh,
            "duration_minutes": t.duration_minutes,
            "status": t.status,
        }
        for t in transactions
    ]

