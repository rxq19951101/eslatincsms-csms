#
# 日志配置
# 支持结构化日志和文件输出
#

import logging
import sys
import json
from datetime import datetime
from typing import Dict, Any
from app.config import get_settings

settings = get_settings()


class JSONFormatter(logging.Formatter):
    """JSON格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # 添加异常信息
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # 添加额外字段
        if hasattr(record, "charger_id"):
            log_obj["charger_id"] = record.charger_id
        if hasattr(record, "transaction_id"):
            log_obj["transaction_id"] = record.transaction_id
        if hasattr(record, "action"):
            log_obj["action"] = record.action
        
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging():
    """设置日志配置"""
    # 获取日志级别
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # 清除现有处理器
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # 设置格式
    if settings.log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器（如果配置了日志文件）
    if settings.log_file:
        file_handler = logging.FileHandler(settings.log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 设置根日志级别
    root_logger.setLevel(log_level)
    
    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器"""
    return logging.getLogger(name)

