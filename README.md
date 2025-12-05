# CSMS - OCPP 1.6J 后端服务

OCPP 充电桩管理系统后端服务，支持 WebSocket、HTTP、MQTT 多种传输方式。

## 功能特性

- ✅ OCPP 1.6 协议完整支持
- ✅ REST API 接口
- ✅ 多传输方式支持（WebSocket、HTTP、MQTT）
- ✅ 充电桩管理
- ✅ 订单管理
- ✅ 消息处理
- ✅ PostgreSQL 数据库
- ✅ Redis 缓存

## 快速开始

### 使用 Docker Compose

```bash
# 创建环境变量文件
cp .env.example .env.production
# 编辑 .env.production 填入配置

# 启动服务
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

### 本地开发

```bash
cd csms
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 端口

- CSMS API: `9000`
- PostgreSQL: `5432`
- Redis: `6379`

## 文档

详细文档请查看 `docs/` 目录。

## 许可证

[您的许可证]
