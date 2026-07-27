# 第三方 API 故障导致支付链路中断分析

**文档编号**：FCR-2023-10-27-001  
**版本**：1.1  
**创建日期**：2023-10-27  
**最后修改**：2023-10-29  
**负责人**：张伟（SRE 团队）  
**审批人**：李明（技术 VP）

---

## 变更记录

| 版本 | 日期       | 修改人 | 变更描述                     |
|------|------------|--------|------------------------------|
| 1.0  | 2023-10-27 | 张伟   | 初始文档创建                 |
| 1.1  | 2023-10-29 | 王芳   | 补充根因分析和修复措施       |

---

## 1. 事件概述

- **发生时间**：2023-10-27 14:23:17 UTC+8  
- **结束时间**：2023-10-27 14:47:52 UTC+8  
- **持续时间**：24 分 35 秒  
- **影响范围**：  
  - 交易系统（Payment Service）全面不可用  
  - 影响用户数：约 12,800 笔待处理订单  
  - 直接经济损失：预估 RMB ￥ 315,000（未完成交易）  
- **严重等级**：P0（最高级别）

---

## 2. 事件时间线

| 时间 (UTC+8)      | 事件描述                                                                 |
|-------------------|--------------------------------------------------------------------------|
| 14:23:17          | 监控系统告警：Payment Service 所有实例返回 HTTP 503 或 504 错误          |
| 14:23:22          | SRE 值班工程师收到 PagerDuty 告警，开始调查                             |
| 14:24:10          | 确认上游第三方支付网关 `api.paypal.com` 响应超时，TCP 连接建立但无响应    |
| 14:25:30          | 尝试切换至备用支付网关 `api.paypal-sandbox.com`，但同样超时              |
| 14:26:45          | 确认第三方 API 完全不可用，通知业务方暂停所有支付请求                    |
| 14:28:00          | 联系第三方技术支持，确认其正在处理故障                                   |
| 14:30:00          | 启动本地 fallback 策略：将支付请求降级为“待处理”状态，存入本地队列       |
| 14:35:00          | 第三方返回确认：内部 DNS 路由配置错误导致所有请求被丢弃                  |
| 14:42:00          | 第三方开始修复，Payment Service 逐步恢复连接                            |
| 14:47:52          | 所有支付请求恢复正常，延迟补发之前积压的待处理订单                      |

---

## 3. 系统架构描述

当前支付链路为典型的 **多层微服务 + 第三方依赖** 架构：

```
[Mobile App]  
    |  
    v  
[API Gateway] (nginx 1.24.0)  
    |  
    v  
[Payment Service] (Spring Boot 2.7.12, 12 个 Pod)  
    |  
    v  
[External Gateway] (通过 `payment-gateway-adapter` 模块调用)  
    |  
    v  
[Third-party: PayPal API] (https://api.paypal.com/v2/checkout/orders)  
```

关键配置参数：

- **连接超时**：5 秒  
- **读取超时**：10 秒  
- **重试策略**：最多 2 次，间隔 1 秒  
- **熔断器**：Hystrix，阈值 50% 错误率，半开窗口 30 秒  
- **队列容量**：本地线程池 `payment-executor`，最大 200 个任务

---

## 4. 根因分析 (RCA)

### 4.1 直接原因
第三方 PayPal API 内部 DNS 配置错误（由第三方运维人员误操作导致），导致所有指向 `api.paypal.com` 的请求被丢弃，TCP 连接虽建立但无任何 HTTP 响应。  
我方日志显示：

```
2023-10-27 14:23:17.123 ERROR [payment-service] c.p.gateway.PayPalAdapter : PayPal API call failed after 2 retries.
java.net.SocketTimeoutException: Read timed out
    at java.base/java.net.SocketInputStream.socketRead0(Native Method)
```

### 4.2 根本原因
1. **缺乏第三方健康检查**：系统未实现定期探测第三方 API 可用性的机制，仅依赖调用时的异常捕获。  
2. **熔断器配置不合理**：Hystrix 的 `circuitBreaker.sleepWindowInMilliseconds` 设置为 30 秒，但第三方故障持续时间超过 20 分钟，熔断器反复开启/关闭，未能彻底阻断请求。  
3. **无备用支付通道**：仅依赖单一第三方提供商（PayPal），未配置备用支付网关（如 Stripe、本地银行直连）。  
4. **降级策略缺失**：当第三方不可用时，系统直接抛出异常，未实现优雅降级（如保存订单到本地队列，待恢复后异步处理）。

### 4.3 触发条件
- 第三方内部变更未同步通知我方  
- 监控告警仅覆盖我方服务，未覆盖第三方依赖状态

---

## 5. 修复措施

### 5.1 短期修复 (已完成)
- 2023-10-28：  
  - 在 Payment Service 中增加第三方健康检查接口，每 30 秒探测一次 `/health` 端点  
  - 修改熔断器参数：`circuitBreaker.sleepWindowInMilliseconds` 改为 120 秒，错误率阈值降低至 40%  
  - 配置日志级别 `DEBUG` 以记录更详细的第三方调用信息

### 5.2 长期修复 (计划中)
- **多提供商支持**：  
  - 集成 Stripe 作为备用支付网关，通过配置开关 `payment.gateway.fallback.enabled=true` 动态切换  
  - 实现一致性哈希路由，将 20% 流量先切换至 Stripe 进行灰度验证

- **本地降级队列**：  
  - 使用 Redis List 作为待处理订单队列，当第三方不可用时，将支付请求存入队列  
  - 定时任务每 10 秒检查队列，恢复后自动补发

- **监控增强**：  
  - 增加 Grafana 面板 `External API Health`，展示第三方可用性、响应时间、错误率  
  - 配置告警规则：第三方错误率 > 5% 持续 2 分钟 → P2 告警

### 5.3 配置示例

```yaml
# application.yml 更新部分
payment:
  gateway:
    primary:
      url: https://api.paypal.com/v2/checkout/orders
      connect-timeout: 3000
      read-timeout: 5000
    fallback:
      enabled: true
      url: https://api.stripe.com/v1/charges
      connect-timeout: 3000
      read-timeout: 5000
    health-check:
      interval: 30s
      endpoint: /health
      timeout: 2000
  queue:
    type: redis
    key: payment:queue:pending
    poll-interval: 10s
```

### 5.4 熔断器参数调整

```java
// HystrixCommandProperties 配置
.setter(
    withCircuitBreakerEnabled(true)
    .withCircuitBreakerRequestVolumeThreshold(10)
    .withCircuitBreakerErrorThresholdPercentage(40)
    .withCircuitBreakerSleepWindowInMilliseconds(120_000)
    .withExecutionTimeoutInMilliseconds(8000)
    .withExecutionIsolationStrategy(ExecutionIsolationStrategy.THREAD)
)
```

---

## 6. 经验教训

1. **依赖管理**：任何第三方 API 都应视为不可靠组件，必须设计熔断、降级、多通道冗余。  
2. **测试覆盖**：本次故障未在灰度环境触发，因为灰度流量仅占总量的 5%，且第三方故障是全局限流。后续需增加“第三方故障注入测试”，每周至少一次。  
3. **沟通流程**：与第三方签订 SLA 后，应建立 7x24 紧急联系人渠道，并定期演练故障响应。  
4. **文档更新**：增加 `docs/failover/payment-gateway-failover.md`，详细描述切换步骤和回滚方案。

---

## 7. 附件

- 日志文件：`/var/log/payment-service/2023-10-27/error.log`  
- 监控截图：Grafana 面板 `Payment API Latency` 时间序列图（见附件图 1）  
- 第三方事故报告：PayPal 官方邮件回复（2023-10-28 09:00）

---

**文档状态**：已完成  
**下次审核日期**：2023-11-27