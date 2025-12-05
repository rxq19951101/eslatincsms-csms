# OCPP 协议检测工具快速开始

## 快速检测实体充电桩

### 步骤 1: 确认 CSMS 正在运行

```bash
curl http://localhost:9000/health
```

应该返回：`{"ok":true,"ts":"..."}`

### 步骤 2: 检查 CSMS 支持的功能

```bash
curl http://localhost:9000/api/ocpp/supported
```

这将显示当前 CSMS 实现支持的所有 OCPP 功能。

### 步骤 3: 运行检测工具

```bash
# 进入 csms 目录
cd csms

# 运行检测（替换 CP-001 为你的充电桩ID）
python app/ocpp_validator.py --charger-id CP-001
```

### 步骤 4: 查看检测报告

检测工具会：
1. 连接充电桩到 CSMS
2. 测试所有必需的 OCPP 消息
3. 生成详细的检测报告

## 示例输出

```
开始检测充电桩: CP-001
✓ 已连接到CSMS: ws://localhost:9000/ocpp?id=CP-001

============================================================
测试：充电桩 → CSMS 消息
============================================================

测试: BootNotification
  描述: 充电桩启动时发送，通知CSMS其配置信息
  必需: 是
  → 发送: BootNotification
  ← 收到响应: {"action":"BootNotification","status":"Accepted",...}

...

================================================================================
OCPP 1.6 协议完整性检测报告
================================================================================
充电桩ID: CP-001
检测时间: 2024-01-15T10:30:00Z
================================================================================

【充电桩 → CSMS 消息测试结果】
  总计: 10
  通过: 7
  必需: 7
  必需通过: 7
  通过率: 70.0%

【合规性评估】
✓ 所有必需的充电桩→CSMS消息都已通过测试
```

## 常见问题

### Q: 充电桩未连接怎么办？

A: 确保：
1. 实体充电桩已配置连接到 CSMS
2. 充电桩ID正确
3. 网络连接正常

### Q: 如何保存检测报告？

A: 使用 `--output` 参数：

```bash
python app/ocpp_validator.py --charger-id CP-001 --output report.txt
```

### Q: 如何检测远程充电桩？

A: 使用 `--csms-url` 参数：

```bash
python app/ocpp_validator.py \
  --charger-id CP-001 \
  --csms-url ws://your-server.com:9000/ocpp
```

## 下一步

1. 查看完整文档：`OCPP_VALIDATION_README.md`
2. 进行端到端测试
3. 检查可选功能的支持情况

