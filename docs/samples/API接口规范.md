# API 接口规范 v2.3

## 通用约定

- **Base URL**: `https://api.internal.company.com/v2`
- **认证方式**: Bearer Token，在 Header 中传递 `Authorization: Bearer <token>`
- **响应格式**:

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "request_id": "uuid"
}
```

错误码规范：

| code | 含义 |
|---|---|
| 0 | 成功 |
| 1001 | 参数校验失败 |
| 1002 | 认证失败 / Token 过期 |
| 1003 | 权限不足 |
| 2001 | 资源不存在 |
| 5000 | 服务器内部错误 |

## 订单相关接口

### POST /orders — 创建订单

```json
{
  "user_id": "u_12345",
  "items": [
    {"sku_id": "sku_001", "quantity": 2}
  ],
  "coupon_code": "SUMMER2024",
  "address_id": "addr_67890"
}
```

返回 `data.order_id`，状态码 201。

### GET /orders/{order_id} — 查询订单

返回订单详情，包括支付状态、物流信息、时间线。

### POST /orders/{order_id}/cancel — 取消订单

仅"待支付"状态的订单可取消。需要二次确认：Header 中传 `X-Confirm: yes`。

## 库存相关接口

### GET /inventory/batch?sku_ids=sku_001,sku_002 — 批量查询库存

**并发限流**: 单 IP 不超过 500 QPS。
**超时设置**: 客户端 read timeout 建议设为 3s。
**降级行为**: 超过限流阈值时返回部分数据（`degraded: true`），不保证完整性。
