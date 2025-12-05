#
# 充电桩管理API
# 新充电桩接入、录入、配置管理
#

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.database import get_db, Charger
from app.core.logging_config import get_logger
from app.core.config import get_settings

settings = get_settings()
logger = get_logger("ocpp_csms")

router = APIRouter()


# ==================== 请求模型 ====================

class CreateChargerRequest(BaseModel):
    """创建充电桩请求"""
    charger_id: str = Field(..., description="充电桩ID")
    vendor: Optional[str] = Field(None, description="厂商")
    model: Optional[str] = Field(None, description="型号")
    serial_number: Optional[str] = Field(None, description="序列号")
    firmware_version: Optional[str] = Field(None, description="固件版本")
    connector_type: str = Field("Type2", description="连接器类型")
    charging_rate: float = Field(7.0, description="充电速率 (kW)")
    latitude: Optional[float] = Field(None, description="纬度")
    longitude: Optional[float] = Field(None, description="经度")
    address: Optional[str] = Field(None, description="地址")
    price_per_kwh: float = Field(2700.0, description="每度电价格 (COP/kWh)")


class UpdateChargerLocationRequest(BaseModel):
    """更新充电桩位置请求"""
    charger_id: str = Field(..., description="充电桩ID")
    latitude: float = Field(..., description="纬度")
    longitude: float = Field(..., description="经度")
    address: str = Field("", description="地址")


class UpdateChargerPricingRequest(BaseModel):
    """更新充电桩定价请求"""
    charger_id: str = Field(..., description="充电桩ID")
    price_per_kwh: float = Field(..., gt=0, description="每度电价格 (COP/kWh)")
    charging_rate: Optional[float] = Field(None, description="充电速率 (kW)")


class UpdateChargerInfoRequest(BaseModel):
    """更新充电桩信息请求"""
    charger_id: str = Field(..., description="充电桩ID")
    vendor: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    connector_type: Optional[str] = None


class ChargerStatus(BaseModel):
    """充电桩状态信息"""
    charger_id: str
    is_connected: bool
    is_configured: bool
    status: str
    last_seen: Optional[str]
    vendor: Optional[str] = None
    model: Optional[str] = None
    has_location: bool = False
    has_pricing: bool = False


# ==================== 工具函数 ====================

def check_charger_connection(charger_id: str) -> bool:
    """检查充电桩是否已连接"""
    from app.core.config import get_settings
    settings = get_settings()
    
    if settings.enable_distributed:
        # 分布式模式
        try:
            from app.ocpp.distributed_connection_manager import distributed_connection_manager
            return distributed_connection_manager.is_connected(charger_id)
        except Exception:
            return False
    else:
        # 单服务器模式
        try:
            from app.ocpp.connection_manager import connection_manager
            return connection_manager.is_connected(charger_id)
        except Exception:
            return False


def get_charger_from_redis(charger_id: str) -> Optional[dict]:
    """从Redis获取充电桩信息"""
    try:
        import redis
        import json
        import os
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        charger_data = redis_client.hget("chargers", charger_id)
        if charger_data:
            return json.loads(charger_data)
        return None
    except Exception as e:
        logger.error(f"从Redis获取充电桩信息失败: {e}")
        return None


# ==================== API端点 ====================

@router.get("/pending", summary="获取待配置的充电桩列表")
def get_pending_chargers(db: Session = Depends(get_db)) -> List[ChargerStatus]:
    """
    获取已连接但未完整配置的充电桩列表
    
    判断标准：
    1. 充电桩已连接（WebSocket在线）
    2. 但数据库中不存在或配置不完整（缺少位置、价格等）
    """
    pending_chargers = []
    
    # 获取所有已连接的充电桩ID
    from app.core.config import get_settings
    settings = get_settings()
    
    if settings.enable_distributed:
        # 分布式模式
        try:
            from app.ocpp.distributed_connection_manager import distributed_connection_manager
            connected_ids = distributed_connection_manager.get_all_connected_chargers()
        except Exception:
            connected_ids = []
    else:
        # 单服务器模式
        try:
            from app.ocpp.connection_manager import connection_manager
            connected_ids = connection_manager.get_all_charger_ids()
        except Exception:
            connected_ids = []
    
    # 检查每个已连接的充电桩
    for charger_id in connected_ids:
        # 从Redis获取实时状态
        redis_charger = get_charger_from_redis(charger_id)
        
        # 从数据库获取配置信息
        db_charger = db.query(Charger).filter(Charger.id == charger_id).first()
        
        # 判断是否需要配置
        is_configured = False
        has_location = False
        has_pricing = False
        
        if db_charger:
            is_configured = True
            has_location = db_charger.latitude is not None and db_charger.longitude is not None
            has_pricing = db_charger.price_per_kwh is not None and db_charger.price_per_kwh > 0
        elif redis_charger:
            # 检查Redis中的数据是否完整
            location = redis_charger.get("location", {})
            has_location = location.get("latitude") is not None and location.get("longitude") is not None
            has_pricing = redis_charger.get("price_per_kwh") is not None and redis_charger.get("price_per_kwh", 0) > 0
        
        # 如果配置不完整，加入待配置列表
        if not is_configured or not has_location or not has_pricing:
            status_info = ChargerStatus(
                charger_id=charger_id,
                is_connected=True,
                is_configured=is_configured,
                status=redis_charger.get("status", "Unknown") if redis_charger else "Unknown",
                last_seen=redis_charger.get("last_seen") if redis_charger else None,
                vendor=redis_charger.get("vendor") if redis_charger else None,
                model=redis_charger.get("model") if redis_charger else None,
                has_location=has_location,
                has_pricing=has_pricing
            )
            pending_chargers.append(status_info)
    
    return pending_chargers


@router.post("/create", summary="创建/录入充电桩")
def create_charger(req: CreateChargerRequest, db: Session = Depends(get_db)) -> dict:
    """
    创建新的充电桩记录
    
    如果充电桩已存在，则更新信息
    """
    # 检查充电桩是否已存在
    charger = db.query(Charger).filter(Charger.id == req.charger_id).first()
    
    if charger:
        # 更新现有充电桩
        if req.vendor:
            charger.vendor = req.vendor
        if req.model:
            charger.model = req.model
        if req.serial_number:
            charger.serial_number = req.serial_number
        if req.firmware_version:
            charger.firmware_version = req.firmware_version
        if req.connector_type:
            charger.connector_type = req.connector_type
        if req.charging_rate:
            charger.charging_rate = req.charging_rate
        if req.latitude is not None:
            charger.latitude = req.latitude
        if req.longitude is not None:
            charger.longitude = req.longitude
        if req.address:
            charger.address = req.address
        if req.price_per_kwh:
            charger.price_per_kwh = req.price_per_kwh
        
        charger.updated_at = datetime.now(timezone.utc)
        charger.is_active = True
    else:
        # 创建新充电桩
        charger = Charger(
            id=req.charger_id,
            vendor=req.vendor,
            model=req.model,
            serial_number=req.serial_number,
            firmware_version=req.firmware_version,
            connector_type=req.connector_type,
            charging_rate=req.charging_rate,
            latitude=req.latitude,
            longitude=req.longitude,
            address=req.address or "",
            price_per_kwh=req.price_per_kwh,
            status="Unknown",
            is_active=True
        )
        db.add(charger)
    
    try:
        db.commit()
        db.refresh(charger)
        
        # 同步更新Redis
        try:
            import redis
            import json
            import os
            
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            
            charger_data = get_charger_from_redis(req.charger_id) or {}
            charger_data.update({
                "id": req.charger_id,
                "vendor": req.vendor,
                "model": req.model,
                "connector_type": req.connector_type,
                "charging_rate": req.charging_rate,
                "price_per_kwh": req.price_per_kwh,
                "location": {
                    "latitude": req.latitude,
                    "longitude": req.longitude,
                    "address": req.address or ""
                }
            })
            
            redis_client.hset("chargers", req.charger_id, json.dumps(charger_data))
        except Exception as e:
            logger.warning(f"同步Redis失败: {e}")
        
        logger.info(f"充电桩 {req.charger_id} 已创建/更新")
        
        return {
            "success": True,
            "message": "充电桩已创建/更新",
            "charger": {
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
    except Exception as e:
        db.rollback()
        logger.error(f"创建充电桩失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建充电桩失败: {str(e)}")


@router.post("/location", summary="设置充电桩位置")
def update_charger_location(req: UpdateChargerLocationRequest, db: Session = Depends(get_db)) -> dict:
    """设置或更新充电桩的地理位置"""
    charger = db.query(Charger).filter(Charger.id == req.charger_id).first()
    
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {req.charger_id} 未找到，请先创建充电桩")
    
    # 更新位置信息
    charger.latitude = req.latitude
    charger.longitude = req.longitude
    charger.address = req.address
    charger.updated_at = datetime.now(timezone.utc)
    
    try:
        db.commit()
        
        # 同步更新Redis
        try:
            import redis
            import json
            import os
            
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            
            charger_data = get_charger_from_redis(req.charger_id) or {"id": req.charger_id}
            charger_data["location"] = {
                "latitude": req.latitude,
                "longitude": req.longitude,
                "address": req.address
            }
            
            redis_client.hset("chargers", req.charger_id, json.dumps(charger_data))
        except Exception as e:
            logger.warning(f"同步Redis失败: {e}")
        
        logger.info(f"充电桩 {req.charger_id} 位置已更新: ({req.latitude}, {req.longitude})")
        
        return {
            "success": True,
            "message": "位置已更新",
            "location": {
                "latitude": req.latitude,
                "longitude": req.longitude,
                "address": req.address
            }
        }
    except Exception as e:
        db.rollback()
        logger.error(f"更新位置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新位置失败: {str(e)}")


@router.post("/pricing", summary="设置充电桩定价")
def update_charger_pricing(req: UpdateChargerPricingRequest, db: Session = Depends(get_db)) -> dict:
    """设置或更新充电桩的价格和充电速率"""
    charger = db.query(Charger).filter(Charger.id == req.charger_id).first()
    
    if not charger:
        raise HTTPException(status_code=404, detail=f"充电桩 {req.charger_id} 未找到，请先创建充电桩")
    
    # 更新价格
    charger.price_per_kwh = req.price_per_kwh
    if req.charging_rate:
        charger.charging_rate = req.charging_rate
    charger.updated_at = datetime.now(timezone.utc)
    
    try:
        db.commit()
        
        # 同步更新Redis
        try:
            import redis
            import json
            import os
            
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            
            charger_data = get_charger_from_redis(req.charger_id) or {"id": req.charger_id}
            charger_data["price_per_kwh"] = req.price_per_kwh
            if req.charging_rate:
                charger_data["charging_rate"] = req.charging_rate
            
            redis_client.hset("chargers", req.charger_id, json.dumps(charger_data))
        except Exception as e:
            logger.warning(f"同步Redis失败: {e}")
        
        logger.info(f"充电桩 {req.charger_id} 价格已更新: {req.price_per_kwh} COP/kWh")
        
        return {
            "success": True,
            "message": "价格已更新",
            "pricing": {
                "price_per_kwh": req.price_per_kwh,
                "charging_rate": charger.charging_rate
            }
        }
    except Exception as e:
        db.rollback()
        logger.error(f"更新价格失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新价格失败: {str(e)}")


@router.get("/{charger_id}/status", summary="获取充电桩状态和配置信息")
def get_charger_status(charger_id: str, db: Session = Depends(get_db)) -> dict:
    """获取充电桩的连接状态和配置完整性"""
    # 检查连接状态
    is_connected = check_charger_connection(charger_id)
    
    # 从Redis获取实时信息
    redis_charger = get_charger_from_redis(charger_id)
    
    # 从数据库获取配置信息
    db_charger = db.query(Charger).filter(Charger.id == charger_id).first()
    
    # 判断配置完整性
    is_configured = db_charger is not None
    has_location = False
    has_pricing = False
    
    if db_charger:
        has_location = db_charger.latitude is not None and db_charger.longitude is not None
        has_pricing = db_charger.price_per_kwh is not None and db_charger.price_per_kwh > 0
    elif redis_charger:
        location = redis_charger.get("location", {})
        has_location = location.get("latitude") is not None and location.get("longitude") is not None
        has_pricing = redis_charger.get("price_per_kwh") is not None and redis_charger.get("price_per_kwh", 0) > 0
    
    return {
        "charger_id": charger_id,
        "is_connected": is_connected,
        "is_configured": is_configured,
        "has_location": has_location,
        "has_pricing": has_pricing,
        "configuration_complete": is_configured and has_location and has_pricing,
        "real_time_info": {
            "status": redis_charger.get("status", "Unknown") if redis_charger else "Unknown",
            "last_seen": redis_charger.get("last_seen") if redis_charger else None,
            "vendor": redis_charger.get("vendor") if redis_charger else None,
            "model": redis_charger.get("model") if redis_charger else None,
        },
        "database_info": {
            "exists": db_charger is not None,
            "location": {
                "latitude": db_charger.latitude if db_charger else None,
                "longitude": db_charger.longitude if db_charger else None,
                "address": db_charger.address if db_charger else None,
            } if db_charger else None,
            "pricing": {
                "price_per_kwh": db_charger.price_per_kwh if db_charger else None,
                "charging_rate": db_charger.charging_rate if db_charger else None,
            } if db_charger else None,
        }
    }

