#
# 本文件实现 csms FastAPI 应用：/ocpp WebSocket 与 /health、/chargers REST。
# 使用 Redis 保存充电桩状态（简化 OCPP 1.6J 流程，测试用途）。

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ocpp_csms")


# ---- App & CORS ----
app = FastAPI(title="Local OCPP 1.6J CSMS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Redis Client ----
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client: redis.Redis = redis.from_url(REDIS_URL, decode_responses=True)

CHARGERS_HASH_KEY = "chargers"
MESSAGES_LIST_KEY = "messages"  # Redis list for messages
ORDERS_HASH_KEY = "orders"  # Redis hash for charging orders

# ---- WebSocket connection registry ----
charger_websockets: Dict[str, WebSocket] = {}


# ---- Helper function to send OCPP messages from CSMS to Charge Point ----
async def send_ocpp_call(charger_id: str, action: str, payload: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    """
    发送OCPP调用从CSMS到充电桩，并等待响应。
    返回响应数据或错误信息。
    """
    ws = charger_websockets.get(charger_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Charger {charger_id} is not connected")
    
    try:
        message = {
            "action": action,
            "payload": payload
        }
        await ws.send_text(json.dumps(message))
        logger.info(f"[{charger_id}] -> CSMS发送OCPP调用: {action}")
        
        # 等待响应（简化版本，实际应该使用消息ID匹配）
        try:
            response = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
            response_data = json.loads(response)
            logger.info(f"[{charger_id}] <- 收到响应: {action}")
            return {"success": True, "data": response_data}
        except asyncio.TimeoutError:
            logger.warning(f"[{charger_id}] OCPP调用超时: {action}")
            return {"success": False, "error": "Timeout waiting for response"}
    except Exception as e:
        logger.error(f"[{charger_id}] 发送OCPP调用失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send OCPP call: {str(e)}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_default_charger(charger_id: str) -> Dict[str, Any]:
    return {
        "id": charger_id,
        "vendor": None,
        "model": None,
        "firmware_version": None,
        "serial_number": None,
        "status": "Unknown",
        "last_seen": now_iso(),
        "location": {
            "latitude": None,
            "longitude": None,
            "address": "",
        },
        "session": {
            "authorized": False,
            "transaction_id": None,
            "meter": 0,
        },
        "connector_type": "Type2",  # 充电头类型: GBT, Type1, Type2, CCS1, CCS2
        "charging_rate": 7.0,  # 充电速率 (kW)
        "price_per_kwh": 2700.0,  # 每度电价格 (COP/kWh)
    }


def migrate_charger_data(charger: Dict[str, Any]) -> Dict[str, Any]:
    """迁移旧数据，补充缺失的新字段，并修复数据不一致问题"""
    # 如果缺少新字段，使用默认值
    if "connector_type" not in charger:
        charger["connector_type"] = "Type2"
    if "charging_rate" not in charger:
        charger["charging_rate"] = 7.0
    if "price_per_kwh" not in charger:
        charger["price_per_kwh"] = 2700.0
    
    # 确保session中有order_id字段（如果不存在）
    if "session" in charger:
        if "order_id" not in charger["session"]:
            charger["session"]["order_id"] = None
        
        # 修复：如果状态是 Available 但 transaction_id 不为 null，清理 transaction_id
        if charger.get("status") == "Available" and charger["session"].get("transaction_id") is not None:
            logger.info(f"[{charger.get('id')}] Auto-fixing: clearing stale transaction_id for Available charger")
            charger["session"]["transaction_id"] = None
            charger["session"]["order_id"] = None
    
    return charger


def load_chargers() -> List[Dict[str, Any]]:
    items = redis_client.hgetall(CHARGERS_HASH_KEY)
    chargers: List[Dict[str, Any]] = []
    for _, val in items.items():
        try:
            charger = json.loads(val)
            # 迁移旧数据，补充缺失字段
            charger = migrate_charger_data(charger)
            # 如果数据有更新，保存回去
            save_charger(charger)
            chargers.append(charger)
        except Exception:
            continue
    return chargers


def save_charger(charger: Dict[str, Any]) -> None:
    """保存充电桩数据到Redis，带错误处理"""
    try:
        redis_client.hset(CHARGERS_HASH_KEY, charger["id"], json.dumps(charger))
    except redis.exceptions.ResponseError as e:
        # Redis配置错误（如MISCONF），记录但不中断流程
        logger.error(f"Redis配置错误，无法保存充电桩 {charger['id']}: {e}")
        logger.warning(f"充电桩数据未保存到Redis，但连接继续: {charger['id']}")
    except Exception as e:
        # 其他Redis错误，记录但不中断流程
        logger.error(f"Redis错误，无法保存充电桩 {charger['id']}: {e}", exc_info=True)
        logger.warning(f"充电桩数据未保存到Redis，但连接继续: {charger['id']}")


# ---- Order Management ----
def create_order(
    order_id: str,
    charger_id: str,
    user_id: str,
    id_tag: str,
    charging_rate: float,
    start_time: str,
) -> Dict[str, Any]:
    """创建充电订单"""
    order = {
        "id": order_id,
        "charger_id": charger_id,
        "user_id": user_id,
        "id_tag": id_tag,
        "charging_rate": charging_rate,
        "start_time": start_time,
        "end_time": None,
        "duration_minutes": None,
        "energy_kwh": None,
        "status": "ongoing",  # ongoing, completed, cancelled
    }
    redis_client.hset(ORDERS_HASH_KEY, order_id, json.dumps(order))
    logger.info(f"Order created: {order_id} for charger {charger_id}")
    return order


def update_order(
    order_id: str,
    end_time: str,
    duration_minutes: float,
    energy_kwh: float,
) -> None:
    """更新订单（结束充电时）"""
    order_data = redis_client.hget(ORDERS_HASH_KEY, order_id)
    if not order_data:
        logger.warning(f"Order not found: {order_id}")
        return
    
    order = json.loads(order_data)
    order["end_time"] = end_time
    order["duration_minutes"] = duration_minutes
    order["energy_kwh"] = energy_kwh
    order["status"] = "completed"
    
    redis_client.hset(ORDERS_HASH_KEY, order_id, json.dumps(order))
    logger.info(f"Order updated: {order_id}, energy: {energy_kwh} kWh, duration: {duration_minutes} min")


def get_order(order_id: str) -> Dict[str, Any] | None:
    """获取单个订单"""
    order_data = redis_client.hget(ORDERS_HASH_KEY, order_id)
    if not order_data:
        return None
    return json.loads(order_data)


def get_orders_by_user(user_id: str) -> List[Dict[str, Any]]:
    """获取用户的所有订单"""
    items = redis_client.hgetall(ORDERS_HASH_KEY)
    orders = []
    for _, val in items.items():
        try:
            order = json.loads(val)
            if order.get("user_id") == user_id:
                orders.append(order)
        except Exception:
            continue
    # 按开始时间倒序排列（最新的在前）
    orders.sort(key=lambda x: x.get("start_time", ""), reverse=True)
    return orders


def get_all_orders() -> List[Dict[str, Any]]:
    """获取所有订单"""
    items = redis_client.hgetall(ORDERS_HASH_KEY)
    orders = []
    for _, val in items.items():
        try:
            orders.append(json.loads(val))
        except Exception:
            continue
    # 按开始时间倒序排列（最新的在前）
    orders.sort(key=lambda x: x.get("start_time", ""), reverse=True)
    return orders


# ---- In-memory active chargers (for quick inspection) ----
active_chargers: Dict[str, Dict[str, Any]] = {}


def update_active(
    charger_id: str,
    *,
    vendor: str | None = None,
    model: str | None = None,
    status: str | None = None,
    txn_id: int | None | str | None = None,
) -> None:
    rec = active_chargers.get(charger_id)
    if rec is None:
        rec = {
            "id": charger_id,
            "vendor": None,
            "model": None,
            "status": "Unknown",
            "last_seen": now_iso(),
            "txn_id": None,
        }
        active_chargers[charger_id] = rec
    if vendor is not None:
        rec["vendor"] = vendor
    if model is not None:
        rec["model"] = model
    if status is not None:
        rec["status"] = status
        # 修复：如果状态变为 Available，自动清理 transaction_id（防止数据不一致）
        if status == "Available" and (txn_id is None or txn_id == ""):
            # 从 Redis 加载充电桩数据并清理 transaction_id
            charger = next((c for c in load_chargers() if c["id"] == charger_id), None)
            if charger:
                session = charger.setdefault("session", {
                    "authorized": False,
                    "transaction_id": None,
                    "meter": 0,
                })
                if session.get("transaction_id") is not None:
                    session["transaction_id"] = None
                    session["order_id"] = None
                    save_charger(charger)
                    logger.info(f"[{charger_id}] Auto-cleared stale transaction_id when status became Available")
    if txn_id is not None or txn_id is None:
        rec["txn_id"] = txn_id
    rec["last_seen"] = now_iso()


class HealthResponse(BaseModel):
    ok: bool
    ts: str


class RemoteStartRequest(BaseModel):
    chargePointId: str
    idTag: str


class RemoteStopRequest(BaseModel):
    chargePointId: str


class RemoteResponse(BaseModel):
    success: bool
    message: str
    details: Dict[str, Any] | None = None


class UpdateLocationRequest(BaseModel):
    chargePointId: str
    latitude: float
    longitude: float
    address: str = ""


class UpdatePriceRequest(BaseModel):
    chargePointId: str
    pricePerKwh: float  # 每度电价格 (COP/kWh)


class CreateMessageRequest(BaseModel):
    userId: str
    username: str
    message: str


class ReplyMessageRequest(BaseModel):
    messageId: str
    reply: str


class GetOrdersRequest(BaseModel):
    userId: str | None = None  # 如果提供，只返回该用户的订单；否则返回所有订单


class GetConfigurationRequest(BaseModel):
    chargePointId: str
    keys: List[str] | None = None  # 如果为空，获取所有配置


class ChangeConfigurationRequest(BaseModel):
    chargePointId: str
    key: str
    value: str


class ResetRequest(BaseModel):
    chargePointId: str
    type: str = "Soft"  # Soft or Hard


class UnlockConnectorRequest(BaseModel):
    chargePointId: str
    connectorId: int


class ChangeAvailabilityRequest(BaseModel):
    chargePointId: str
    connectorId: int
    type: str  # Inoperative or Operative


class SetChargingProfileRequest(BaseModel):
    chargePointId: str
    connectorId: int
    csChargingProfiles: Dict[str, Any]


class ClearChargingProfileRequest(BaseModel):
    chargePointId: str
    id: int | None = None
    connectorId: int | None = None
    chargingProfilePurpose: str | None = None
    stackLevel: int | None = None


class GetDiagnosticsRequest(BaseModel):
    chargePointId: str
    location: str
    retries: int | None = None
    retryInterval: int | None = None
    startTime: str | None = None
    stopTime: str | None = None


class UpdateFirmwareRequest(BaseModel):
    chargePointId: str
    location: str
    retrieveDate: str
    retryInterval: int | None = None
    retries: int | None = None


class ReserveNowRequest(BaseModel):
    chargePointId: str
    connectorId: int
    expiryDate: str
    idTag: str
    reservationId: int
    parentIdTag: str | None = None


class CancelReservationRequest(BaseModel):
    chargePointId: str
    reservationId: int


@app.get("/health", response_model=HealthResponse, tags=["REST"])
def health() -> HealthResponse:
    """
    Health check endpoint.
    Returns: {"ok": true, "ts": "ISO timestamp"}
    """
    return HealthResponse(ok=True, ts=now_iso())


@app.get("/api/ocpp/supported", tags=["REST"])
def get_supported_ocpp_features() -> Dict[str, Any]:
    """
    获取当前CSMS实现支持的OCPP功能列表。
    用于检测实体充电桩时了解CSMS的能力。
    """
    return {
        "ocpp_version": "1.6J",
        "chargePoint_to_csms": {
            "supported": [
                "BootNotification",
                "Heartbeat",
                "StatusNotification",
                "Authorize",
                "StartTransaction",
                "StopTransaction",
                "MeterValues",
                "FirmwareStatusNotification",
                "DiagnosticsStatusNotification",
                "DataTransfer"
            ],
            "required_messages": 7,
            "supported_count": 10,
            "status": "all_required_supported",
            "note": "包含所有必需消息和部分可选消息"
        },
        "csms_to_chargePoint": {
            "supported": [
                "RemoteStartTransaction",
                "RemoteStopTransaction",
                "GetConfiguration",
                "ChangeConfiguration",
                "Reset",
                "UnlockConnector",
                "ChangeAvailability",
                "SetChargingProfile",
                "ClearChargingProfile",
                "GetDiagnostics",
                "UpdateFirmware",
                "ReserveNow",
                "CancelReservation"
            ],
            "required_messages": 2,
            "supported_count": 13,
            "status": "all_required_supported",
            "note": "所有功能通过REST API实现"
        },
        "api_endpoints": {
            "chargePoint_to_csms": "WebSocket: /ocpp",
            "csms_to_chargePoint": [
                "POST /api/remoteStart",
                "POST /api/remoteStop",
                "POST /api/getConfiguration",
                "POST /api/changeConfiguration",
                "POST /api/reset",
                "POST /api/unlockConnector",
                "POST /api/changeAvailability",
                "POST /api/setChargingProfile",
                "POST /api/clearChargingProfile",
                "POST /api/getDiagnostics",
                "POST /api/updateFirmware",
                "POST /api/reserveNow",
                "POST /api/cancelReservation"
            ]
        },
        "validation_tool": {
            "available": True,
            "path": "csms/app/ocpp_validator.py",
            "description": "使用 ocpp_validator.py 工具检测实体充电桩"
        }
    }


@app.get("/chargers", tags=["REST"])
def chargers_list() -> List[Dict[str, Any]]:
    """
    List all chargers from Redis.
    Returns: [{"id": str, "status": str, "last_seen": str, "session": {...}}, ...]
    """
    return load_chargers()


@app.post("/api/updateLocation", response_model=RemoteResponse, tags=["REST"])
async def update_location(req: UpdateLocationRequest) -> RemoteResponse:
    """
    Update charger location (latitude, longitude, address).
    """
    charger = next((c for c in load_chargers() if c["id"] == req.chargePointId), None)
    if not charger:
        charger = get_default_charger(req.chargePointId)
        save_charger(charger)
    
    charger["location"] = {
        "latitude": req.latitude,
        "longitude": req.longitude,
        "address": req.address,
    }
    save_charger(charger)
    
    logger.info(f"[{req.chargePointId}] Location updated: lat={req.latitude}, lng={req.longitude}")
    
    return RemoteResponse(
        success=True,
        message="Location updated successfully",
        details={"chargePointId": req.chargePointId, "location": charger["location"]},
    )


@app.post("/api/updatePrice", response_model=RemoteResponse, tags=["REST"])
async def update_price(req: UpdatePriceRequest) -> RemoteResponse:
    """
    Update charger price per kWh.
    """
    charger = next((c for c in load_chargers() if c["id"] == req.chargePointId), None)
    if not charger:
        charger = get_default_charger(req.chargePointId)
        save_charger(charger)
    
    charger["price_per_kwh"] = req.pricePerKwh
    save_charger(charger)
    
    logger.info(f"[{req.chargePointId}] Price updated: {req.pricePerKwh} COP/kWh")
    
    return RemoteResponse(
        success=True,
        message="Price updated successfully",
        details={"chargePointId": req.chargePointId, "pricePerKwh": req.pricePerKwh},
    )


@app.post("/api/remoteStart", response_model=RemoteResponse, tags=["REST"])
async def remote_start(req: RemoteStartRequest) -> RemoteResponse:
    """
    Remote start transaction by sending Authorize + StartTransaction.
    Requires chargePointId and idTag.
    
    NOTE: This is a simplified implementation that mimics user actions.
    In a full OCPP implementation, CSMS would send RemoteStartTransaction to the charger.
    """
    ws = charger_websockets.get(req.chargePointId)
    if not ws:
        # Fallback：如果充电桩未连接 WebSocket，则直接在 Redis 中模拟充电状态
        charger = next((c for c in load_chargers() if c["id"] == req.chargePointId), None)
        if charger is None:
            charger = get_default_charger(req.chargePointId)
        session = charger.setdefault("session", {
            "authorized": False,
            "transaction_id": None,
            "meter": 0,
        })
        tx_id = int(datetime.now().timestamp())
        charger["status"] = "Charging"
        session["authorized"] = True
        session["transaction_id"] = tx_id
        charger["last_seen"] = now_iso()
        
        # 创建充电订单
        charging_rate = charger.get("charging_rate", 7.0)
        order_id = f"order_{tx_id}"
        start_time = now_iso()
        create_order(
            order_id=order_id,
            charger_id=req.chargePointId,
            user_id=req.idTag,  # 使用idTag作为user_id
            id_tag=req.idTag,
            charging_rate=charging_rate,
            start_time=start_time,
        )
        # 将订单ID保存到session中，以便停止时使用
        session["order_id"] = order_id
        
        save_charger(charger)
        update_active(req.chargePointId, status="Charging", txn_id=tx_id)
        logger.info(
            f"[{req.chargePointId}] RemoteStart fallback: WebSocket missing, simulated transaction {tx_id}, order {order_id}"
        )
        return RemoteResponse(
            success=True,
            message="Charging started (simulated)",
            details={"transactionId": tx_id, "idTag": req.idTag, "orderId": order_id, "simulated": True},
        )
    try:
        # Step 1: Send Authorize to verify the idTag
        auth_call = json.dumps({
            "action": "Authorize",
            "payload": {"idTag": req.idTag},
        })
        await ws.send_text(auth_call)
        logger.info(f"[{req.chargePointId}] Sent Authorize for idTag={req.idTag}")
        
        # Step 2: Generate transaction ID and send StartTransaction
        tx_id = int(datetime.now().timestamp())
        start_call = json.dumps({
            "action": "StartTransaction",
            "payload": {"transactionId": tx_id},
        })
        await ws.send_text(start_call)
        logger.info(f"[{req.chargePointId}] Sent StartTransaction with txId={tx_id}")
        
        # 创建充电订单
        charger = next((c for c in load_chargers() if c["id"] == req.chargePointId), None)
        if charger is None:
            charger = get_default_charger(req.chargePointId)
        charging_rate = charger.get("charging_rate", 7.0)
        order_id = f"order_{tx_id}"
        start_time = now_iso()
        create_order(
            order_id=order_id,
            charger_id=req.chargePointId,
            user_id=req.idTag,  # 使用idTag作为user_id
            id_tag=req.idTag,
            charging_rate=charging_rate,
            start_time=start_time,
        )
        # 将订单ID保存到charger的session中
        session = charger.setdefault("session", {
            "authorized": False,
            "transaction_id": None,
            "meter": 0,
        })
        session["order_id"] = order_id
        save_charger(charger)
        
        return RemoteResponse(
            success=True,
            message="Charging started successfully",
            details={"transactionId": tx_id, "idTag": req.idTag, "orderId": order_id},
        )
    except Exception as e:
        logger.error(f"[{req.chargePointId}] Error starting transaction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/remoteStop", response_model=RemoteResponse, tags=["REST"])
async def remote_stop(req: RemoteStopRequest) -> RemoteResponse:
    """
    Remote stop transaction via RemoteStopTransaction OCPP call.
    Requires chargePointId (transactionId is inferred from active session).
    
    NOTE: In a full OCPP implementation, this would use CallResult/CallError
    with unique message IDs. This simplified version directly sends JSON.
    """
    ws = charger_websockets.get(req.chargePointId)
    charger = next((c for c in load_chargers() if c["id"] == req.chargePointId), None)
    if charger is None:
        charger = get_default_charger(req.chargePointId)
    if not ws:
        session = charger.setdefault("session", {
            "authorized": False,
            "transaction_id": None,
            "meter": 0,
        })
        txn_id = session.get("transaction_id")
        order_id = session.get("order_id")
        
        # 更新订单：计算电量和时长
        if order_id:
            order = get_order(order_id)
            if order and order.get("status") == "ongoing":
                start_time_str = order.get("start_time")
                end_time_str = now_iso()
                
                # 计算时长（分钟）
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                duration_seconds = (end_time - start_time).total_seconds()
                duration_minutes = duration_seconds / 60.0
                
                # 计算电量（kWh）= 充电速率（kW）× 时长（小时）
                charging_rate = order.get("charging_rate", 7.0)
                energy_kwh = charging_rate * (duration_minutes / 60.0)
                
                update_order(
                    order_id=order_id,
                    end_time=end_time_str,
                    duration_minutes=round(duration_minutes, 2),
                    energy_kwh=round(energy_kwh, 2),
                )
        
        session["transaction_id"] = None
        session["authorized"] = False
        session["order_id"] = None
        charger["status"] = "Available"
        charger["last_seen"] = now_iso()
        session["meter"] = session.get("meter", 0)
        save_charger(charger)
        update_active(req.chargePointId, status="Available", txn_id=None)
        logger.info(
            f"[{req.chargePointId}] RemoteStop fallback: WebSocket missing, simulated stop for tx={txn_id}, order={order_id}"
        )
        return RemoteResponse(
            success=True,
            message="Charging stopped (simulated)",
            details={"transactionId": txn_id, "orderId": order_id, "simulated": True},
        )
    # Get transaction ID and order ID from active chargers
    txn_id = None
    order_id = None
    if charger:
        session = charger.get("session", {})
        txn_id = session.get("transaction_id")
        order_id = session.get("order_id")
    if not txn_id:
        return RemoteResponse(
            success=False,
            message="No active transaction found",
            details=None,
        )
    try:
        # Send RemoteStopTransaction (simplified format)
        call = json.dumps({
            "action": "RemoteStopTransaction",
            "transactionId": txn_id,
        })
        await ws.send_text(call)
        
        # 注意：在实际的OCPP实现中，应该等待StopTransaction响应后再更新订单
        # 这里简化处理，假设会成功停止
        # 订单更新会在WebSocket的StopTransaction处理中完成
        
        return RemoteResponse(
            success=True,
            message="RemoteStopTransaction sent",
            details={"action": "RemoteStopTransaction", "transactionId": txn_id, "orderId": order_id, "sent": True},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/getConfiguration", response_model=RemoteResponse, tags=["REST"])
async def get_configuration(req: GetConfigurationRequest) -> RemoteResponse:
    """
    获取充电桩配置参数。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "GetConfiguration",
            {"key": req.keys} if req.keys else {}
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="GetConfiguration sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in GetConfiguration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/changeConfiguration", response_model=RemoteResponse, tags=["REST"])
async def change_configuration(req: ChangeConfigurationRequest) -> RemoteResponse:
    """
    更改充电桩配置参数。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "ChangeConfiguration",
            {"key": req.key, "value": req.value}
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="ChangeConfiguration sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ChangeConfiguration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset", response_model=RemoteResponse, tags=["REST"])
async def reset_charger(req: ResetRequest) -> RemoteResponse:
    """
    重置充电桩（软重启或硬重启）。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "Reset",
            {"type": req.type}
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="Reset sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Reset: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/unlockConnector", response_model=RemoteResponse, tags=["REST"])
async def unlock_connector(req: UnlockConnectorRequest) -> RemoteResponse:
    """
    解锁连接器。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "UnlockConnector",
            {"connectorId": req.connectorId}
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="UnlockConnector sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in UnlockConnector: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/changeAvailability", response_model=RemoteResponse, tags=["REST"])
async def change_availability(req: ChangeAvailabilityRequest) -> RemoteResponse:
    """
    更改充电桩或连接器的可用性。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "ChangeAvailability",
            {"connectorId": req.connectorId, "type": req.type}
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="ChangeAvailability sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ChangeAvailability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/setChargingProfile", response_model=RemoteResponse, tags=["REST"])
async def set_charging_profile(req: SetChargingProfileRequest) -> RemoteResponse:
    """
    设置充电配置文件。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "SetChargingProfile",
            {
                "connectorId": req.connectorId,
                "csChargingProfiles": req.csChargingProfiles
            }
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="SetChargingProfile sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in SetChargingProfile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clearChargingProfile", response_model=RemoteResponse, tags=["REST"])
async def clear_charging_profile(req: ClearChargingProfileRequest) -> RemoteResponse:
    """
    清除充电配置文件。
    """
    try:
        payload = {}
        if req.id is not None:
            payload["id"] = req.id
        if req.connectorId is not None:
            payload["connectorId"] = req.connectorId
        if req.chargingProfilePurpose is not None:
            payload["chargingProfilePurpose"] = req.chargingProfilePurpose
        if req.stackLevel is not None:
            payload["stackLevel"] = req.stackLevel
        
        result = await send_ocpp_call(
            req.chargePointId,
            "ClearChargingProfile",
            payload
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="ClearChargingProfile sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ClearChargingProfile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/getDiagnostics", response_model=RemoteResponse, tags=["REST"])
async def get_diagnostics(req: GetDiagnosticsRequest) -> RemoteResponse:
    """
    获取诊断信息。
    """
    try:
        payload = {"location": req.location}
        if req.retries is not None:
            payload["retries"] = req.retries
        if req.retryInterval is not None:
            payload["retryInterval"] = req.retryInterval
        if req.startTime is not None:
            payload["startTime"] = req.startTime
        if req.stopTime is not None:
            payload["stopTime"] = req.stopTime
        
        result = await send_ocpp_call(
            req.chargePointId,
            "GetDiagnostics",
            payload
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="GetDiagnostics sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in GetDiagnostics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/updateFirmware", response_model=RemoteResponse, tags=["REST"])
async def update_firmware(req: UpdateFirmwareRequest) -> RemoteResponse:
    """
    更新固件。
    """
    try:
        payload = {
            "location": req.location,
            "retrieveDate": req.retrieveDate
        }
        if req.retryInterval is not None:
            payload["retryInterval"] = req.retryInterval
        if req.retries is not None:
            payload["retries"] = req.retries
        
        result = await send_ocpp_call(
            req.chargePointId,
            "UpdateFirmware",
            payload
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="UpdateFirmware sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in UpdateFirmware: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reserveNow", response_model=RemoteResponse, tags=["REST"])
async def reserve_now(req: ReserveNowRequest) -> RemoteResponse:
    """
    预约充电。
    """
    try:
        payload = {
            "connectorId": req.connectorId,
            "expiryDate": req.expiryDate,
            "idTag": req.idTag,
            "reservationId": req.reservationId
        }
        if req.parentIdTag is not None:
            payload["parentIdTag"] = req.parentIdTag
        
        result = await send_ocpp_call(
            req.chargePointId,
            "ReserveNow",
            payload
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="ReserveNow sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ReserveNow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cancelReservation", response_model=RemoteResponse, tags=["REST"])
async def cancel_reservation(req: CancelReservationRequest) -> RemoteResponse:
    """
    取消预约。
    """
    try:
        result = await send_ocpp_call(
            req.chargePointId,
            "CancelReservation",
            {"reservationId": req.reservationId}
        )
        return RemoteResponse(
            success=result.get("success", False),
            message="CancelReservation sent" if result.get("success") else "Failed",
            details=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in CancelReservation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/messages", response_model=RemoteResponse, tags=["REST"])
async def create_message(req: CreateMessageRequest) -> RemoteResponse:
    """
    Create a new support message from user.
    """
    message_id = f"msg_{int(datetime.now().timestamp() * 1000)}"
    message_data = {
        "id": message_id,
        "userId": req.userId,
        "username": req.username,
        "message": req.message,
        "reply": None,
        "created_at": now_iso(),
        "replied_at": None,
        "status": "pending",
    }
    
    # Save to Redis list
    redis_client.lpush(MESSAGES_LIST_KEY, json.dumps(message_data))
    # Keep only last 100 messages
    redis_client.ltrim(MESSAGES_LIST_KEY, 0, 99)
    
    logger.info(f"New message from user {req.username} ({req.userId}): {req.message[:50]}")
    
    return RemoteResponse(
        success=True,
        message="Message created successfully",
        details={"messageId": message_id, "message": message_data},
    )


@app.get("/api/messages", tags=["REST"])
def list_messages() -> List[Dict[str, Any]]:
    """
    List all support messages (admin view).
    """
    items = redis_client.lrange(MESSAGES_LIST_KEY, 0, -1)
    messages = []
    for val in items:
        try:
            messages.append(json.loads(val))
        except Exception:
            continue
    # Reverse to show newest first
    messages.reverse()
    return messages


@app.post("/api/messages/reply", response_model=RemoteResponse, tags=["REST"])
async def reply_message(req: ReplyMessageRequest) -> RemoteResponse:
    """
    Reply to a support message.
    """
    # Find message in Redis
    items = redis_client.lrange(MESSAGES_LIST_KEY, 0, -1)
    found = False
    
    for i, val in enumerate(items):
        try:
            msg = json.loads(val)
            if msg["id"] == req.messageId:
                msg["reply"] = req.reply
                msg["replied_at"] = now_iso()
                msg["status"] = "replied"
                # Update in Redis
                redis_client.lset(MESSAGES_LIST_KEY, i, json.dumps(msg))
                found = True
                logger.info(f"Replied to message {req.messageId}: {req.reply[:50]}")
                break
        except Exception:
            continue
    
    if not found:
        raise HTTPException(status_code=404, detail="Message not found")
    
    return RemoteResponse(
        success=True,
        message="Reply sent successfully",
        details=None,
    )


@app.get("/api/orders", tags=["REST"])
def get_orders(userId: str | None = None) -> List[Dict[str, Any]]:
    """
    Get charging orders.
    If userId is provided, returns only orders for that user.
    Otherwise, returns all orders.
    """
    if userId:
        return get_orders_by_user(userId)
    else:
        return get_all_orders()


@app.get("/api/orders/current", tags=["REST"])
def get_current_order(chargePointId: str = Query(...), transactionId: int | None = Query(None)) -> Dict[str, Any]:
    """
    Get current ongoing order for a charger.
    If transactionId is provided, find order by transaction ID.
    Otherwise, find the latest ongoing order for the charger.
    """
    if transactionId:
        # 尝试通过transaction_id找到订单（订单ID格式为 order_{transactionId}）
        order_id = f"order_{transactionId}"
        order = get_order(order_id)
        if order:
            # 返回订单，即使状态不是ongoing（可能刚创建）
            return order
    
    # 如果没有提供transactionId或找不到，查找充电桩的订单
    charger = next((c for c in load_chargers() if c["id"] == chargePointId), None)
    if charger:
        session = charger.get("session", {})
        order_id = session.get("order_id")
        if order_id:
            order = get_order(order_id)
            if order:
                return order
    
    # 如果都找不到，尝试查找该充电桩的所有订单，返回最新的进行中订单
    all_orders = get_all_orders()
    charger_orders = [o for o in all_orders if o.get("charger_id") == chargePointId]
    if charger_orders:
        # 按开始时间排序，返回最新的
        charger_orders.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        # 优先返回ongoing状态的，否则返回最新的
        ongoing_order = next((o for o in charger_orders if o.get("status") == "ongoing"), None)
        if ongoing_order:
            return ongoing_order
        return charger_orders[0]
    
    raise HTTPException(status_code=404, detail="No order found")


@app.websocket("/ocpp")
async def ocpp_ws(ws: WebSocket, id: str = Query(..., description="Charger ID")):
    # Enforce subprotocol negotiation for OCPP 1.6J
    requested_proto = (ws.headers.get("sec-websocket-protocol") or "").strip()
    requested = [p.strip() for p in requested_proto.split(",") if p.strip()]
    if "ocpp1.6" not in requested:
        # Refuse if client does not offer ocpp1.6
        await ws.close(code=1002)
        return
    await ws.accept(subprotocol="ocpp1.6")
    # Register WebSocket connection
    charger_websockets[id] = ws
    logger.info(f"[{id}] WebSocket connected, subprotocol=ocpp1.6")
    
    charger = None
    try:
        # Initialize charger record
        charger = next((c for c in load_chargers() if c["id"] == id), None)
        if charger is None:
            charger = get_default_charger(id)
            try:
                save_charger(charger)
                logger.info(f"[{id}] New charger registered")
            except Exception as e:
                logger.warning(f"[{id}] 无法保存充电桩到Redis（但继续连接）: {e}")
        # initialize in-memory record
        update_active(id)

        await ws.send_text(json.dumps({"result": "Connected", "id": id}))

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await ws.send_text(json.dumps({"error": "Invalid JSON"}))
                continue

            action = str(msg.get("action", "")).strip()
            payload = msg.get("payload", {})
            
            logger.info(f"[{id}] <- OCPP {action} | payload={json.dumps(payload)}")

            charger = next((c for c in load_chargers() if c["id"] == id), get_default_charger(id))
            charger["last_seen"] = now_iso()

            # Simplified handlers for demo
            if action == "BootNotification":
                try:
                    charger["status"] = "Available"
                    vendor = str(payload.get("vendor", ""))
                    model = str(payload.get("model", ""))
                    firmware_version = str(payload.get("firmwareVersion", ""))
                    serial_number = str(payload.get("serialNumber", ""))
                    
                    # 更新充电桩信息
                    charger["vendor"] = vendor if vendor else charger.get("vendor")
                    charger["model"] = model if model else charger.get("model")
                    charger["firmware_version"] = firmware_version if firmware_version else charger.get("firmware_version")
                    charger["serial_number"] = serial_number if serial_number else charger.get("serial_number")
                    
                    update_active(id, vendor=vendor or None, model=model or None, status="Available")
                    save_charger(charger)  # 这里可能失败，但不影响响应
                    
                    logger.info(f"[{id}] BootNotification: vendor={vendor}, model={model}, firmware={firmware_version}, serial={serial_number}")
                except Exception as e:
                    logger.error(f"[{id}] BootNotification处理错误（但继续响应）: {e}", exc_info=True)
                
                # 无论Redis是否成功，都返回正常的OCPP响应
                resp = {
                    "action": action,
                    "status": "Accepted",
                    "currentTime": now_iso(),
                    "interval": 30,
                }
                logger.info(f"[{id}] -> OCPP BootNotificationResponse | status=Accepted")
                await ws.send_text(json.dumps(resp))

            elif action == "Heartbeat":
                update_active(id)
                save_charger(charger)
                resp = {"action": action, "currentTime": now_iso()}
                logger.info(f"[{id}] -> OCPP HeartbeatResponse | currentTime={now_iso()}")
                await ws.send_text(json.dumps(resp))

            elif action == "StatusNotification":
                new_status = str(payload.get("status", "Unknown"))
                charger["status"] = new_status
                # 修复：如果状态变为 Available，自动清理 transaction_id
                if new_status == "Available":
                    session = charger.setdefault("session", {
                        "authorized": False,
                        "transaction_id": None,
                        "meter": 0,
                    })
                    if session.get("transaction_id") is not None:
                        logger.info(f"[{id}] Auto-cleared transaction_id when status changed to Available")
                        session["transaction_id"] = None
                        session["order_id"] = None
                update_active(id, status=new_status)
                save_charger(charger)
                logger.info(f"[{id}] -> OCPP StatusNotificationAccepted | status={new_status}")
                await ws.send_text(json.dumps({"action": action}))

            elif action == "Authorize":
                id_tag = str(payload.get("idTag", ""))
                charger["session"]["authorized"] = True if id_tag else False
                save_charger(charger)
                auth_status = "Accepted" if id_tag else "Invalid"
                logger.info(f"[{id}] -> OCPP AuthorizeResponse | status={auth_status}")
                await ws.send_text(
                    json.dumps(
                        {
                            "action": action,
                            "idTagInfo": {"status": auth_status},
                        }
                    )
                )

            elif action == "StartTransaction":
                tx_id = payload.get("transactionId") or int(datetime.now().timestamp())
                id_tag = str(payload.get("idTag", ""))
                charger["session"]["transaction_id"] = tx_id
                charger["status"] = "Charging"
                
                # 创建充电订单
                charging_rate = charger.get("charging_rate", 7.0)
                order_id = f"order_{tx_id}"
                start_time = now_iso()
                create_order(
                    order_id=order_id,
                    charger_id=id,
                    user_id=id_tag,  # 使用idTag作为user_id
                    id_tag=id_tag,
                    charging_rate=charging_rate,
                    start_time=start_time,
                )
                charger["session"]["order_id"] = order_id
                
                update_active(id, status="Charging", txn_id=tx_id)
                save_charger(charger)
                logger.info(f"[{id}] -> OCPP StartTransactionResponse | txId={tx_id}, orderId={order_id}")
                await ws.send_text(
                    json.dumps(
                        {
                            "action": action,
                            "transactionId": tx_id,
                            "idTagInfo": {"status": "Accepted"},
                        }
                    )
                )

            elif action == "MeterValues":
                meter = int(payload.get("meter", charger["session"].get("meter", 0)))
                charger["session"]["meter"] = meter
                save_charger(charger)
                logger.info(f"[{id}] -> OCPP MeterValuesAccepted | meter={meter}")
                await ws.send_text(json.dumps({"action": action}))

            elif action == "StopTransaction":
                tx_id = charger["session"].get("transaction_id")
                order_id = charger["session"].get("order_id")
                
                # 更新订单：计算电量和时长
                if order_id:
                    order = get_order(order_id)
                    if order and order.get("status") == "ongoing":
                        start_time_str = order.get("start_time")
                        end_time_str = now_iso()
                        
                        # 计算时长（分钟）
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        duration_seconds = (end_time - start_time).total_seconds()
                        duration_minutes = duration_seconds / 60.0
                        
                        # 计算电量（kWh）= 充电速率（kW）× 时长（小时）
                        charging_rate = order.get("charging_rate", 7.0)
                        energy_kwh = charging_rate * (duration_minutes / 60.0)
                        
                        update_order(
                            order_id=order_id,
                            end_time=end_time_str,
                            duration_minutes=round(duration_minutes, 2),
                            energy_kwh=round(energy_kwh, 2),
                        )
                
                charger["session"]["transaction_id"] = None
                charger["session"]["order_id"] = None
                charger["status"] = "Available"
                update_active(id, status="Available", txn_id=None)
                save_charger(charger)
                logger.info(f"[{id}] -> OCPP StopTransactionResponse | txId={tx_id}, orderId={order_id}")
                await ws.send_text(
                    json.dumps(
                        {
                            "action": action,
                            "stopped": True,
                            "transactionId": tx_id,
                            "idTagInfo": {"status": "Accepted"},
                        }
                    )
                )

            elif action == "FirmwareStatusNotification":
                status = str(payload.get("status", "Unknown"))
                logger.info(f"[{id}] FirmwareStatusNotification: {status}")
                save_charger(charger)
                await ws.send_text(json.dumps({"action": action}))

            elif action == "DiagnosticsStatusNotification":
                status = str(payload.get("status", "Unknown"))
                logger.info(f"[{id}] DiagnosticsStatusNotification: {status}")
                save_charger(charger)
                await ws.send_text(json.dumps({"action": action}))

            elif action == "DataTransfer":
                vendor_id = str(payload.get("vendorId", ""))
                message_id = str(payload.get("messageId", ""))
                data = payload.get("data")
                logger.info(f"[{id}] DataTransfer from {vendor_id}, messageId={message_id}")
                save_charger(charger)
                # 返回接受状态
                await ws.send_text(json.dumps({
                    "action": action,
                    "status": "Accepted",
                    "data": None
                }))

            else:
                await ws.send_text(json.dumps({"error": "UnknownAction", "action": action}))

    except WebSocketDisconnect:
        # Mark last seen on disconnect
        logger.info(f"[{id}] WebSocket disconnected")
        if charger:
            try:
                charger["last_seen"] = now_iso()
                save_charger(charger)
            except Exception:
                pass  # Redis错误不影响断开连接
        update_active(id)
    except Exception as e:
        logger.error(f"[{id}] WebSocket处理错误: {e}", exc_info=True)
        # 尝试发送错误响应（如果连接还活着）
        try:
            # 检查是否是Redis错误，如果是，发送更友好的错误信息
            error_detail = str(e)
            if "MISCONF" in error_detail or "Redis" in error_detail:
                error_detail = "Redis配置错误，请联系管理员"
            
            await ws.send_text(json.dumps({
                "error": "InternalError", 
                "detail": error_detail[:200]  # 限制错误信息长度
            }))
        except Exception:
            # 连接可能已关闭，忽略
            pass
    finally:
        # Unregister WebSocket connection
        charger_websockets.pop(id, None)
        logger.info(f"[{id}] WebSocket unregistered")
        try:
            await ws.close()
        except Exception:
            pass


# ---- 注册 API v1 路由 ----
try:
    from app.api.v1 import api_router
    app.include_router(api_router)
    logger.info("API v1 路由已注册")
except ImportError as e:
    logger.warning(f"API v1 路由注册失败（导入错误）: {e}，某些功能可能无法使用")
except Exception as e:
    logger.error(f"API v1 路由注册出错: {e}", exc_info=True)

