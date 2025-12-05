#!/usr/bin/env python3
#
# 数据库初始化脚本
# 创建初始数据和管理员账户
#

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db, SessionLocal, engine
from app.config import get_settings

def main():
    """初始化数据库"""
    settings = get_settings()
    
    print(f"初始化数据库: {settings.database_url}")
    
    # 创建所有表
    init_db()
    print("✓ 数据库表创建完成")
    
    # 可以在这里添加初始数据
    # 例如：创建默认管理员账户、默认配置等
    
    print("✓ 数据库初始化完成")

if __name__ == "__main__":
    main()

