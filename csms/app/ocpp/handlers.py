#
# OCPP消息处理器
# 处理从充电桩接收的OCPP消息
#

import json
from datetime import datetime, timezone
from typing import Dict, Any
from app.ocpp.connection_manager import connection_manager
from app.database import get_db, Charger, Transaction, Order, Session
from app.database.models import MeterValue as MeterValueModel
import logging

logger = logging.getLogger("ocpp_csms")


def now_iso() -> str:
    """获取当前ISO格式时间"""
    return datetime.now(timezone.utc).isoformat()


class OCPPHandler:
    """OCPP消息处理器"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def handle_boot_notification(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理BootNotification消息"""
        vendor = str(payload.get("vendor", ""))
        model = str(payload.get("model", ""))
        
        # 更新或创建充电桩记录
        charger = self.db.query(Charger).filter(Charger.id == charger_id).first()
        if not charger:
            charger = Charger(
                id=charger_id,
                vendor=vendor or None,
                model=model or None,
                status="Available",
                last_seen=datetime.now(timezone.utc)
            )
            self.db.add(charger)
            logger.info(f"[{charger_id}] 新充电桩注册")
        else:
            charger.vendor = vendor or charger.vendor
            charger.model = model or charger.model
            charger.status = "Available"
            charger.last_seen = datetime.now(timezone.utc)
        
        self.db.commit()
        
        return {
            "action": "BootNotification",
            "status": "Accepted",
            "currentTime": now_iso(),
            "interval": 30,
        }
    
    async def handle_heartbeat(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理Heartbeat消息"""
        charger = self.db.query(Charger).filter(Charger.id == charger_id).first()
        if charger:
            charger.last_seen = datetime.now(timezone.utc)
            self.db.commit()
        
        return {
            "action": "Heartbeat",
            "currentTime": now_iso()
        }
    
    async def handle_status_notification(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理StatusNotification消息"""
        new_status = str(payload.get("status", "Unknown"))
        
        charger = self.db.query(Charger).filter(Charger.id == charger_id).first()
        if charger:
            charger.status = new_status
            charger.last_seen = datetime.now(timezone.utc)
            
            # 如果状态变为Available，清理事务ID
            if new_status == "Available":
                # 可以在这里添加清理逻辑
                pass
            
            self.db.commit()
        
        return {"action": "StatusNotification"}
    
    async def handle_authorize(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理Authorize消息"""
        id_tag = str(payload.get("idTag", ""))
        auth_status = "Accepted" if id_tag else "Invalid"
        
        return {
            "action": "Authorize",
            "idTagInfo": {"status": auth_status}
        }
    
    async def handle_start_transaction(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理StartTransaction消息"""
        tx_id = payload.get("transactionId") or int(datetime.now().timestamp())
        id_tag = str(payload.get("idTag", ""))
        
        charger = self.db.query(Charger).filter(Charger.id == charger_id).first()
        if not charger:
            charger = Charger(
                id=charger_id,
                status="Charging",
                last_seen=datetime.now(timezone.utc)
            )
            self.db.add(charger)
        
        # 创建事务
        transaction = Transaction(
            charger_id=charger_id,
            transaction_id=tx_id,
            id_tag=id_tag,
            user_id=id_tag,
            start_time=datetime.now(timezone.utc),
            status="ongoing",
            charging_rate=charger.charging_rate,
            price_per_kwh=charger.price_per_kwh
        )
        self.db.add(transaction)
        
        # 创建订单
        order = Order(
            id=f"order_{tx_id}",
            transaction_id=transaction.id,
            charger_id=charger_id,
            user_id=id_tag,
            id_tag=id_tag,
            start_time=datetime.now(timezone.utc),
            charging_rate=charger.charging_rate,
            price_per_kwh=charger.price_per_kwh,
            status="ongoing"
        )
        self.db.add(order)
        
        charger.status = "Charging"
        charger.last_seen = datetime.now(timezone.utc)
        
        self.db.commit()
        
        logger.info(f"[{charger_id}] 充电事务开始: txId={tx_id}, orderId={order.id}")
        
        return {
            "action": "StartTransaction",
            "transactionId": tx_id,
            "idTagInfo": {"status": "Accepted"}
        }
    
    async def handle_stop_transaction(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理StopTransaction消息"""
        tx_id = payload.get("transactionId")
        
        # 查找事务
        transaction = self.db.query(Transaction).filter(
            Transaction.charger_id == charger_id,
            Transaction.transaction_id == tx_id
        ).first()
        
        if transaction:
            transaction.end_time = datetime.now(timezone.utc)
            transaction.status = "completed"
            
            # 计算时长和电量
            if transaction.start_time:
                duration = (transaction.end_time - transaction.start_time).total_seconds() / 60.0
                transaction.duration_minutes = round(duration, 2)
                
                if transaction.charging_rate:
                    transaction.energy_kwh = round(
                        transaction.charging_rate * (duration / 60.0), 2
                    )
            
            # 更新订单
            order = self.db.query(Order).filter(Order.transaction_id == transaction.id).first()
            if order:
                order.end_time = transaction.end_time
                order.duration_minutes = transaction.duration_minutes
                order.energy_kwh = transaction.energy_kwh
                order.status = "completed"
        
        # 更新充电桩状态
        charger = self.db.query(Charger).filter(Charger.id == charger_id).first()
        if charger:
            charger.status = "Available"
            charger.last_seen = datetime.now(timezone.utc)
        
        self.db.commit()
        
        return {
            "action": "StopTransaction",
            "stopped": True,
            "transactionId": tx_id,
            "idTagInfo": {"status": "Accepted"}
        }
    
    async def handle_meter_values(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理MeterValues消息"""
        meter = int(payload.get("meter", 0))
        tx_id = payload.get("transactionId")
        
        if tx_id:
            transaction = self.db.query(Transaction).filter(
                Transaction.charger_id == charger_id,
                Transaction.transaction_id == tx_id
            ).first()
            
            if transaction:
                # 创建计量值记录
                meter_value = MeterValueModel(
                    transaction_id=transaction.id,
                    timestamp=datetime.now(timezone.utc),
                    value=meter
                )
                self.db.add(meter_value)
                self.db.commit()
        
        return {"action": "MeterValues"}
    
    async def handle_firmware_status_notification(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理FirmwareStatusNotification消息"""
        status = str(payload.get("status", "Unknown"))
        logger.info(f"[{charger_id}] 固件状态通知: {status}")
        return {"action": "FirmwareStatusNotification"}
    
    async def handle_diagnostics_status_notification(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理DiagnosticsStatusNotification消息"""
        status = str(payload.get("status", "Unknown"))
        logger.info(f"[{charger_id}] 诊断状态通知: {status}")
        return {"action": "DiagnosticsStatusNotification"}
    
    async def handle_data_transfer(self, charger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理DataTransfer消息"""
        vendor_id = str(payload.get("vendorId", ""))
        message_id = str(payload.get("messageId", ""))
        logger.info(f"[{charger_id}] 数据传输: vendor={vendor_id}, messageId={message_id}")
        
        return {
            "action": "DataTransfer",
            "status": "Accepted",
            "data": None
        }
    
    async def handle_message(self, charger_id: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理OCPP消息路由"""
        handler_map = {
            "BootNotification": self.handle_boot_notification,
            "Heartbeat": self.handle_heartbeat,
            "StatusNotification": self.handle_status_notification,
            "Authorize": self.handle_authorize,
            "StartTransaction": self.handle_start_transaction,
            "StopTransaction": self.handle_stop_transaction,
            "MeterValues": self.handle_meter_values,
            "FirmwareStatusNotification": self.handle_firmware_status_notification,
            "DiagnosticsStatusNotification": self.handle_diagnostics_status_notification,
            "DataTransfer": self.handle_data_transfer,
        }
        
        handler = handler_map.get(action)
        if handler:
            return await handler(charger_id, payload)
        else:
            raise ValueError(f"Unknown action: {action}")

