#
# 安全认证和授权
#

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from app.config import get_settings

settings = get_settings()

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer认证
security = HTTPBearer()

# API Key认证（用于充电桩认证）
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """验证令牌"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> Dict[str, Any]:
    """获取当前用户（从JWT令牌）"""
    token = credentials.credentials
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> bool:
    """验证API密钥（用于充电桩认证）"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少API密钥",
        )
    
    # TODO: 从数据库验证API密钥
    # 这里简化处理，实际应该从数据库查询
    valid_keys = {"charger-api-key-1", "charger-api-key-2"}  # 生产环境应从配置或数据库读取
    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的API密钥",
        )
    return True


def verify_charger_id(charger_id: str, api_key: Optional[str] = None) -> bool:
    """验证充电桩ID和API密钥的关联"""
    # TODO: 实现充电桩ID和API密钥的关联验证
    # 生产环境应该从数据库验证充电桩和API密钥的关联关系
    return True


# OCPP WebSocket认证
def verify_ocpp_charger_id(charger_id: str, headers: Dict[str, str]) -> bool:
    """验证OCPP WebSocket连接的充电桩ID"""
    # 可以基于IP白名单、API密钥等进行验证
    # TODO: 实现更严格的认证机制
    return True

