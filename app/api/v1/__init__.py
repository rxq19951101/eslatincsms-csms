#
# API v1路由
# 组织所有v1版本的API端点
#

from fastapi import APIRouter
from app.api.v1 import chargers, transactions, orders, ocpp_control, admin, charger_management

# 创建v1路由器
api_router = APIRouter(prefix="/api/v1", tags=["API v1"])

# 注册路由
api_router.include_router(chargers.router, prefix="/chargers", tags=["充电桩管理"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["事务管理"])
api_router.include_router(orders.router, prefix="/orders", tags=["订单管理"])
api_router.include_router(ocpp_control.router, prefix="/ocpp", tags=["OCPP控制"])
api_router.include_router(admin.router, prefix="/admin", tags=["管理功能"])
api_router.include_router(charger_management.router, prefix="/charger-management", tags=["新充电桩管理"])

