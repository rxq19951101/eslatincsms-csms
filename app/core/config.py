#
# 配置管理
# 使用pydantic-settings进行配置验证和管理
#

from pydantic_settings import BaseSettings
from typing import List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基础配置
    app_name: str = "OCPP 1.6J CSMS"
    app_version: str = "1.0.0"
    environment: str = "development"  # development, staging, production
    debug: bool = False
    
    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 9000
    
    # 数据库配置
    database_url: str = "postgresql://local:local@localhost:5432/ocpp"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    db_echo: bool = False
    
    # Redis配置
    redis_url: str = "redis://localhost:6379/0"
    redis_decode_responses: bool = True
    
    # 分布式部署配置
    enable_distributed: bool = False  # 是否启用分布式模式
    server_id: Optional[str] = None  # 服务器ID（自动生成或手动指定）
    
    # 安全配置
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # CORS配置
    cors_origins: List[str] = ["*"]  # 生产环境应限制具体域名
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]
    
    # TLS/SSL配置
    enable_tls: bool = False
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    
    # WebSocket配置
    ws_ping_interval: int = 20
    ws_ping_timeout: int = 10
    ws_max_connections: int = 1000
    enable_websocket_transport: bool = False  # 是否启用 WebSocket 传输（默认关闭，可通过环境变量启用）
    
    # HTTP传输配置
    enable_http_transport: bool = False  # 是否启用 HTTP 传输（默认关闭，可通过环境变量启用）
    http_ocpp_endpoint: str = "/ocpp"  # HTTP OCPP 端点前缀
    
    # MQTT传输配置（默认通信模式）
    enable_mqtt_transport: bool = True  # 是否启用 MQTT 传输（默认启用）
    mqtt_broker_host: str = "localhost"  # MQTT broker 地址
    mqtt_broker_port: int = 1883  # MQTT broker 端口
    mqtt_username: Optional[str] = None  # MQTT 用户名（可选）
    mqtt_password: Optional[str] = None  # MQTT 密码（可选）
    mqtt_topic_prefix: str = "ocpp"  # MQTT 主题前缀
    
    # OCPP配置
    ocpp_heartbeat_interval: int = 30
    ocpp_message_timeout: int = 5
    ocpp_max_retries: int = 3
    
    # 日志配置
    log_level: str = "INFO"
    log_format: str = "json"  # json, text
    log_file: Optional[str] = None
    
    # 监控配置
    enable_metrics: bool = True
    metrics_path: str = "/metrics"
    
    # API配置
    api_v1_prefix: str = "/api/v1"
    docs_url: Optional[str] = "/docs"
    redoc_url: Optional[str] = "/redoc"
    
    # 速率限制
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    
    # 充电桩配置
    default_charging_rate: float = 7.0  # kW
    default_price_per_kwh: float = 2700.0  # COP/kWh
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例（单例）"""
    return Settings()

