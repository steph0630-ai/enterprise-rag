# RESTful API 错误码定义与异常处理标准

| 版本 | 修订日期 | 修订人 | 修订内容 |
|------|---------|--------|---------|
| 1.0  | 2024-05-10 | 张伟 | 初始版本，定义核心错误码体系 |
| 1.1  | 2024-08-22 | 李明 | 新增限流与认证相关错误码 |
| 1.2  | 2025-02-14 | 王芳 | 统一错误响应结构，增加全局异常处理规范 |

**负责人：** 王芳（技术架构组）  
**适用范围：** 全公司所有微服务项目，包括订单系统、用户中心、支付网关等  
**生效日期：** 2025-03-01

---

## 1. 概述

本规范定义了公司在所有 RESTful API 实现中必须遵循的错误码体系及异常响应格式。  
目的：统一前后端、服务间调用的错误处理方式，降低排障成本，提升系统可观测性。

所有 API 必须返回符合本规范的错误响应，不得直接抛出系统级异常（如 500 空响应）。

---

## 2. 通用错误响应结构

所有错误响应使用 HTTP 状态码，并包含统一的 JSON Body：

```json
{
    "code": "ORDER_4001",
    "message": "订单金额不能为负数",
    "detail": "Received amount: -100.00",
    "timestamp": "2025-02-14T10:30:00.123+08:00",
    "path": "/api/v1/orders",
    "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | String | 是 | 业务错误码，格式为 `{模块}_{数字}` |
| message | String | 是 | 用户友好提示（用于前端展示，长度≤128字符） |
| detail | String | 否 | 调试用详细信息（生产环境可省略，用于日志和排查） |
| timestamp | String | 是 | ISO 8601 格式时间戳，精确到毫秒 |
| path | String | 是 | 请求路径 |
| requestId | String | 是 | 全链路追踪 ID，由网关生成 |

---

## 3. 错误码分类规则

错误码由 `模块前缀` + `4位数字` 组成，数字范围按以下规则分配：

| 范围 | 分类 | 说明 |
|------|------|------|
| 1000–1999 | 通用错误 | 参数校验、请求格式等基础问题 |
| 2000–2999 | 认证与授权 | 登录、Token、权限相关 |
| 3000–3999 | 业务逻辑错误 | 特定业务规则违反（如库存不足） |
| 4000–4999 | 资源冲突 | 重复创建、版本冲突等 |
| 5000–5999 | 外部依赖错误 | 第三方服务超时、调用失败 |
| 6000–6999 | 限流与频率控制 | 请求过于频繁 |

### 模块前缀对照表

| 模块 | 前缀 | 示例 |
|------|------|------|
| 用户中心 | USER | USER_2001 |
| 订单系统 | ORDER | ORDER_3005 |
| 支付网关 | PAY | PAY_5002 |
| 商品服务 | PRODUCT | PRODUCT_4003 |
| 通用错误 | COMMON | COMMON_1000 |

---

## 4. 核心错误码定义

### 4.1 通用错误（1000–1999）

| 错误码 | HTTP 状态码 | message | 触发条件 |
|--------|-------------|---------|----------|
| COMMON_1000 | 400 | 请求参数格式错误 | JSON 解析失败、缺少必填字段 |
| COMMON_1001 | 400 | 参数校验失败 | 业务规则校验不通过（如数值越界） |
| COMMON_1002 | 415 | 不支持的 Content-Type | 请求头 Content-Type 不是 application/json |
| COMMON_1003 | 405 | 请求方法不允许 | 如对只读接口发送 POST |
| COMMON_1004 | 404 | 资源未找到 | 请求路径不存在 |

### 4.2 认证与授权（2000–2999）

| 错误码 | HTTP 状态码 | message | 触发条件 |
|--------|-------------|---------|----------|
| USER_2001 | 401 | 未授权，请重新登录 | Token 缺失或过期 |
| USER_2002 | 401 | Token 无效 | Token 签名不合法 |
| USER_2003 | 403 | 权限不足 | 用户角色无权限访问该接口 |
| USER_2004 | 401 | 账号或密码错误 | 登录验证失败 |

### 4.3 业务逻辑错误（3000–3999）

| 错误码 | HTTP 状态码 | message | 触发条件 |
|--------|-------------|---------|----------|
| ORDER_3001 | 400 | 商品库存不足 | 请求数量 > 可用库存 |
| ORDER_3002 | 400 | 订单状态不允许操作 | 如取消已发货订单 |
| ORDER_3003 | 400 | 优惠券已过期 | 优惠券有效期已过 |
| ORDER_3004 | 400 | 订单金额计算异常 | 前端金额与后端计算不一致 |
| PAY_3001 | 400 | 支付金额与订单金额不符 | 支付回调金额校验失败 |

---

## 5. 异常处理实现规范

### 5.1 全局异常拦截器（Spring Boot 示例）

使用 `@RestControllerAdvice` 统一捕获异常，转换为标准错误响应：

```java
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationException(
            MethodArgumentNotValidException ex,
            HttpServletRequest request) {
        String detail = ex.getBindingResult().getFieldErrors().stream()
                .map(e -> e.getField() + ":" + e.getDefaultMessage())
                .collect(Collectors.joining(", "));
        ErrorResponse error = ErrorResponse.builder()
                .code("COMMON_1001")
                .message("参数校验失败")
                .detail(detail)
                .path(request.getRequestURI())
                .requestId(MDC.get("requestId"))
                .build();
        return ResponseEntity.status(400).body(error);
    }

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ErrorResponse> handleBusinessException(
            BusinessException ex,
            HttpServletRequest request) {
        ErrorResponse error = ErrorResponse.builder()
                .code(ex.getErrorCode())
                .message(ex.getMessage())
                .detail(ex.getDetail())
                .path(request.getRequestURI())
                .requestId(MDC.get("requestId"))
                .build();
        return ResponseEntity.status(ex.getHttpStatus()).body(error);
    }
}
```

### 5.2 自定义异常类

所有业务异常继承自 `BusinessException`，强制携带错误码：

```java
public class BusinessException extends RuntimeException {
    private final String errorCode;
    private final int httpStatus;
    private final String detail;

    public BusinessException(String errorCode, String message, int httpStatus, String detail) {
        super(message);
        this.errorCode = errorCode;
        this.httpStatus = httpStatus;
        this.detail = detail;
    }

    // getters omitted for brevity
}
```

### 5.3 调用示例（服务层）

```java
public void createOrder(CreateOrderRequest request) {
    // 校验库存
    Product product = productClient.getProduct(request.getProductId());
    if (product.getStock() < request.getQuantity()) {
        throw new BusinessException(
            "ORDER_3001",
            "商品库存不足",
            400,
            String.format("Available stock: %d, requested: %d", product.getStock(), request.getQuantity())
        );
    }
    // ... 创建订单逻辑
}
```

---

## 6. 最佳实践与常见问题

### 6.1 错误码使用原则

1. **不重复使用 HTTP 状态码**：状态码仅用于粗粒度分类（如 4xx/5xx），业务细节必须由 `code` 表达。
2. **message 区分用户与开发者**：`message` 面向最终用户，保持简洁友好；`detail` 面向开发者，包含调试信息。
3. **生产环境安全**：生产环境应隐藏敏感信息（如数据库错误堆栈），`detail` 字段可省略或仅记录日志。

### 6.2 常见违规示例

| 错误实现 | 问题 | 正确做法 |
|----------|------|----------|
| 直接返回 500 空响应 | 无法定位问题 | 返回 `COMMON_1000` 或自定义错误码 |
| 返回 HTML 错误页 | 前端无法解析 | 始终返回 JSON |
| 暴露 SQL 错误信息 | 安全风险 | 记录日志，返回通用错误码 |

### 6.3 日志记录要求

所有异常必须记录到 ELK 日志系统，日志格式要求：

