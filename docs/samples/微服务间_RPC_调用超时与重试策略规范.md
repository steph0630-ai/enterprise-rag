# 微服务间 RPC 调用超时与重试策略规范

| 版本 | 日期       | 修订人   | 变更描述               |
|------|------------|----------|------------------------|
| V1.0 | 2024-08-20 | 张明     | 初始版本               |
| V1.1 | 2024-11-05 | 李娜     | 新增熔断与降级联动说明 |
| V1.2 | 2025-03-10 | 王强     | 更新超时参数推荐值     |

**负责人**：张明（架构组）、李娜（SRE 组）  
**生效日期**：2025-03-15  
**适用范围**：所有基于 gRPC 和 Dubbo 的微服务间同步 RPC 调用

---

## 1. 概述

为确保微服务架构下调用链路的稳定性与容错性，避免因单个服务超时或临时故障导致级联雪崩，本规范定义 RPC 调用的超时时间、重试次数、重试间隔以及熔断降级的标准配置策略。

所有服务在接入生产环境前，必须按照本规范设置 RPC 客户端参数。非功能性需求（如超时、重试）的配置应独立于业务代码，通过配置中心（如 Apollo、Nacos）动态下发。

## 2. 超时策略

### 2.1 超时层级

RPC 调用超时分为以下三个层级，优先级由高到低：

| 层级       | 配置位置                 | 说明                           |
|------------|--------------------------|--------------------------------|
| 方法级     | 客户端 `@RpcTimeout` 注解 | 针对特定接口或方法定制         |
| 接口级     | 服务接口的 `timeout` 属性  | 同一接口下所有方法默认值       |
| 全局默认值 | 框架配置文件（如 `application.yml`） | 兜底配置，所有未指定方法的超时值 |

### 2.2 超时时间推荐值

基于内部压测结果（P99 延迟不超过 500ms 的线上数据），推荐超时时间如下：

| 调用类型       | 超时时间（ms） | 适用场景                     |
|----------------|----------------|------------------------------|
| 读操作（查询） | 2000           | 用户信息查询、订单状态查询   |
| 写操作（非事务）| 3000           | 创建订单、更新库存           |
| 写操作（事务） | 5000           | 跨服务分布式事务（TCC/ Saga）|
| 批量操作       | 10000          | 批量导入、导出、报表生成     |
| 同步阻塞调用   | 1500           | 短平快的内部数据校验         |

**注意**：超时时间应小于上游服务的超时时间（通常上游服务的超时为本服务的 1.5~2 倍），避免因本服务超时未响应导致上游资源堆积。

### 2.3 配置示例

**gRPC (Java) 客户端配置：**

```yaml
# application.yml
grpc:
  client:
    user-service:
      address: static://user-service:9090
      negotiation-type: plaintext
      timeout: 2000ms
      method-config:
        - name: GetUserById
          timeout: 1500ms
        - name: BatchCreateUsers
          timeout: 10000ms
```

**Dubbo (Java) 消费者配置：**

```xml
<dubbo:reference id="orderService" interface="com.example.OrderService" timeout="3000" retries="0"/>
```

## 3. 重试策略

### 3.1 重试条件

仅当满足以下所有条件时，客户端才应发起重试：
- 调用返回**可重试的异常**（如 `DEADLINE_EXCEEDED`、`UNAVAILABLE`、`CANCELLED`）
- 调用是**幂等操作**（Idempotent）
- 当前调用**未超过最大重试次数**

**不可重试的异常**：`INVALID_ARGUMENT`、`ALREADY_EXISTS`、`PERMISSION_DENIED`、`NOT_FOUND` 等表示业务错误的异常。

### 3.2 重试参数

| 参数           | 推荐值 | 说明                                       |
|----------------|--------|--------------------------------------------|
| 最大重试次数   | 1~3    | 读操作建议 2，写操作建议 1（非事务写）     |
| 重试间隔       | 50ms   | 固定间隔，避免突发流量冲击                 |
| 重试超时       | 等同于原超时 | 每次重试独立计时，总耗时不超过原超时 × 重试次数 |
| 退避策略       | 固定退避 | 不推荐指数退避，避免长尾延迟               |

**重要**：写操作（特别是涉及事务、扣减库存等关键业务）默认关闭重试（`retries=0`），除非业务明确保证幂等。

### 3.3 重试配置示例

**gRPC 重试配置：**

```yaml
# retry-policy.yaml
retryPolicy:
  maxAttempts: 3
  initialBackoff: 50ms
  maxBackoff: 200ms
  backoffMultiplier: 1.0
  retryableStatusCodes:
    - UNAVAILABLE
    - DEADLINE_EXCEEDED
    - CANCELLED
```

**Java 代码级重试（Spring Retry）：**

```java
@Retryable(
    value = {ServiceUnavailableException.class, DeadlineExceededException.class},
    maxAttempts = 3,
    backoff = @Backoff(delay = 50, maxDelay = 200, multiplier = 1.0)
)
public User getUserById(Long userId) {
    // RPC 调用代码
}
```

## 4. 熔断与降级联动

### 4.1 熔断触发条件

当某接口的**错误率**在时间窗口内超过阈值时，应触发熔断：

| 指标           | 推荐值 | 说明                            |
|----------------|--------|---------------------------------|
| 错误率阈值     | 50%    | 最近 10 秒内错误请求占比        |
| 最小请求数     | 5      | 防止统计样本过小导致误判        |
| 熔断持续时间   | 30s    | 熔断后等待 30s 再尝试半开状态   |
| 半开成功请求数 | 3      | 半开状态下连续成功 3 次后关闭熔断 |

### 4.2 降级策略

熔断期间，应提供降级响应（Fallback），避免调用方长时间等待：

- **读取降级**：返回缓存数据（如 Redis 缓存）或默认值（空列表、0）
- **写入降级**：写入 MQ 异步处理，或直接返回失败（配合业务侧兜底逻辑）

**示例：Hystrix / Resilience4j 降级方法**

```java
@HystrixCommand(fallbackMethod = "getUserFallback")
public User getUserById(Long userId) {
    return userServiceClient.getUserById(userId);
}

public User getUserFallback(Long userId, Throwable t) {
    log.warn("getUserById fallback triggered, userId={}, error={}", userId, t.getMessage());
    // 返回缓存中的用户数据
    return userCache.get(userId);
}
```

## 5. 监控与告警

所有 RPC 调用必须接入统一监控（Prometheus + Grafana），重点关注以下指标：

| 指标名称                  | 告警阈值                   | 说明                       |
|---------------------------|----------------------------|----------------------------|
| `rpc_request_total`       | 无（用于容量规划）         | 总请求数                   |
| `rpc_request_duration_ms` | P99 > 2000ms               | 请求延迟                   |
| `rpc_error_total`         | 错误率 > 5%（5分钟内）     | 错误请求数                 |
| `rpc_retry_total`         | 重试次数 > 10/分钟/接口    | 重试次数过多可能表明下游故障 |
| `rpc_circuit_breaker_open`| 熔断器打开持续时间 > 30s   | 熔断器状态                 |

**告警通知渠道**：P0 级告警推送至钉钉/企微机器人并电话通知，P1 级仅推送至即时通讯群组。

## 6. 变更管理

### 6.1 超时/重试参数变更流程

1. 开发者在配置中心修改参数（如 Apollo namespace）
2. 在预发环境（Staging）灰度验证 24 小时
3. 观察监控指标（延迟、错误率、重试次数）无异常
4. 提交变更工单，经架构组审批后全量发布
5. 变更后持续观察 48 小时，确保无副作用

### 6.2 禁止行为

- 禁止在生产环境随意调大超时时间（超过 10s）
- 禁止在非幂