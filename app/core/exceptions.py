#
# 异常处理
# 统一的异常处理和错误响应格式
#

from typing import Any, Dict, Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

logger = logging.getLogger("ocpp_csms")


class OCPPException(HTTPException):
    """OCPP协议异常基类"""
    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code or "OCPP_ERROR"


class ChargerNotFoundException(OCPPException):
    """充电桩未找到异常"""
    def __init__(self, charger_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"充电桩 {charger_id} 未找到",
            error_code="CHARGER_NOT_FOUND"
        )


class ChargerNotConnectedException(OCPPException):
    """充电桩未连接异常"""
    def __init__(self, charger_id: str):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"充电桩 {charger_id} 未连接",
            error_code="CHARGER_NOT_CONNECTED"
        )


class OCPPMessageException(OCPPException):
    """OCPP消息异常"""
    def __init__(self, action: str, error_code: str, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OCPP消息错误: {action} - {detail}",
            error_code=error_code
        )


class TransactionNotFoundException(OCPPException):
    """事务未找到异常"""
    def __init__(self, transaction_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"事务 {transaction_id} 未找到",
            error_code="TRANSACTION_NOT_FOUND"
        )


class AuthorizationException(OCPPException):
    """授权异常"""
    def __init__(self, id_tag: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"ID标签 {id_tag} 未授权",
            error_code="AUTHORIZATION_FAILED"
        )


# 异常处理器
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTP异常处理器"""
    logger.error(f"HTTP异常: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": getattr(exc, "error_code", "HTTP_ERROR"),
                "message": exc.detail,
                "status_code": exc.status_code
            }
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """验证异常处理器"""
    logger.error(f"验证错误: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求数据验证失败",
                "details": exc.errors()
            }
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """通用异常处理器"""
    logger.exception(f"未处理的异常: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "detail": str(exc) if request.app.debug else None
            }
        }
    )

