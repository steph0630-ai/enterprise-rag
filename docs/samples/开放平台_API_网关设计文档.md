# 开放平台 API 网关设计文档

| 文档版本 | 修订日期    | 修订内容                     | 修订人   |
|----------|-------------|------------------------------|----------|
| V1.0     | 2024-05-20  | 初稿创建                     | 张三     |
| V1.1     | 2024-06-10  | 增加限流策略及熔断配置       | 李四     |
| V1.2     | 2024-07-01  | 更新鉴权流程与签名算法       | 王五     |

**负责人**：李四（架构组）  
**审核人**：赵六（平台技术总监）

---

## 1. 概述

开放平台 API 网关作为企业对外服务的统一入口，负责所有第三方合作伙伴请求的路由分发、安全认证、流量控制以及协议转换。本设计文档适用于 v3.2.x 版本的网关系统，目标群体为后端开发工程师及运维人员。

## 2. 系统架构

### 2.1 总体架构图

```text
[外部客户端]
     |
     | (HTTPS)
     v
[全局负载均衡器 (SLB)] 
     |
     v
[API 网关集群 (Nginx + Lua / OpenResty)]
     |
     |---> [鉴权服务]        (独立微服务，Redis 缓存)
     |---> [限流 & 熔断模块]  (基于 Redis + Lua 脚本)
     |---> [路由转发]         (根据 URL 与 AppId 分发)
     |
     v
[后端业务服务]  -->  [消息队列 (Kafka)]  -->  [日志与监控]
```

### 2.2 组件职责

| 组件名称             | 职责说明                                                                 |
|----------------------|--------------------------------------------------------------------------|
| SLB                  | 四层负载均衡，TLS 终止，对外暴露固定 VIP                                 |
| API 网关节点         | 请求入口，执行鉴权、限流、路由转发，记录访问日志                         |
| 鉴权服务             | 验证 `AppId` 与 `AppSecret` 配对，签发/验证 Access Token                 |
| 限流/熔断模块        | 基于令牌桶算法对 API 级别/用户级别进行流量控制，支持断路器模式            |
| 后端业务服务         | 实际提供业务逻辑的微服务集群，通过 RPC 或 HTTP 暴露接口                  |
| 监控与日志           | 全量请求日志打入 Kafka，最终入 Elasticsearch；Prometheus 采集指标         |

## 3. 核心功能设计

### 3.1 鉴权流程

所有 API 请求必须携带以下 Header：

- `X-App-Id`: 第三方应用唯一标识
- `X-Timestamp`: 当前 Unix 时间戳（秒）
- `X-Signature`: 签名值，算法为 `HMAC-SHA256(Secret, Method + URI + Body + Timestamp)`

**鉴权步骤**：

1. 网关检查 `X-Timestamp` 是否在 ±300 秒内，超出视为过期。
2. 根据 `X-App-Id` 从 Redis 中获取 `AppSecret`（命中缓存）或回查数据库。
3. 使用 `AppSecret` 计算签名并与 `X-Signature` 比较。
4. 若通过则生成临时 `Access Token`（有效期 600 秒），放入请求 Header 透传至后端。

```python
# 示例：Python 签名计算
import hashlib
import hmac

def generate_signature(method: str, uri: str, body: str, timestamp: int, secret: str) -> str:
    raw = f"{method}\n{uri}\n{body}\n{timestamp}"
    return hmac.new(secret.encode('utf-8'), raw.encode('utf-8'), hashlib.sha256).hexdigest()
```

### 3.2 限流与熔断策略

#### 3.2.1 限流规则（以 API 级别为例）

采用令牌桶算法，每个 API 独立配置，存储在 Redis 的 Hash 结构中。

```lua
-- 限流 Lua 脚本片段 (OpenResty)
local key = "rate_limit:" .. api_id .. ":" .. ngx.var.binary_remote_addr
local rate = 50        -- 每秒令牌数
local capacity = 100   -- 桶容量
local now = ngx.time()
local token_key = key .. ":tokens"
local timestamp_key = key .. ":ts"

-- 使用 Redis EVAL 执行原子操作
local res = redis:eval([[
    local tokens = tonumber(redis.call('get', KEYS[1]))
    local last_ts = tonumber(redis.call('get', KEYS[2]))
    if not tokens then
        tokens = ARGV[2]
        last_ts = ARGV[1]
    end
    local delta = tonumber(ARGV[1]) - last_ts
    tokens = math.min(tonumber(ARGV[2]), tokens + delta * tonumber(ARGV[3]))
    if tokens < 1 then
        return 0
    else
        redis.call('set', KEYS[1], tokens - 1)
        redis.call('set', KEYS[2], ARGV[1])
        return 1
    end
]], {token_key, timestamp_key}, now, capacity, rate)

if res == 0 then
    ngx.status = 429
    ngx.say('{"code":429,"message":"Too Many Requests"}')
    return ngx.exit(429)
end
```

**配置表（示例）**：

| API 路径              | 速率 (QPS) | 桶容量 | 超时时间 (秒) |
|-----------------------|------------|--------|---------------|
| `/v1/order/create`    | 200        | 400    | 60            |
| `/v1/user/info`       | 1000       | 2000   | 60            |
| `/v1/payment/callback`| 50         | 100    | 120           |

#### 3.2.2 熔断机制

基于滑动窗口的错误率统计，窗口大小 30 秒，错误率阈值 50%。当错误率超过阈值时，熔断器进入 `OPEN` 状态，所有请求直接返回 503，持续 10 秒后尝试半开。

```yaml
# 熔断配置示例 (YAML)
circuit_breaker:
  enabled: true
  sliding_window_size: 30         # 秒
  failure_rate_threshold: 0.5     # 50%
  open_state_duration: 10         # 秒
  half_open_max_requests: 3
```

### 3.3 路由转发

网关根据 `Host` 和 `URI` 前缀进行路由匹配，支持动态路由表刷新（基于 etcd 或 Nacos）。

```nginx
# Nginx 路由配置片段
upstream order_service {
    server 10.0.1.10:8080 weight=5;
    server 10.0.1.11:8080 weight=5;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    location /v1/order/ {
        set $upstream_order_service "order_service";
        proxy_pass http://$upstream_order_service;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-Id $request_id;
    }

    location /v1/user/ {
        proxy_pass http://user_service;
    }
}
```

## 4. 高可用与部署

### 4.1 部署拓扑

- 网关集群：至少 3 个节点，每个节点 4C8G，部署 OpenResty 1.21.4.1。
- Redis 集群：6 节点（3主3从），用于存储限流状态和 Token 缓存。
- 鉴权服务：无状态集群，水平扩展，部署于 Kubernetes。

### 4.2 健康检查

网关节点每 5 秒向 etcd 上报心跳，若连续 3 次未上报，SLB 自动摘除节点。

```bash
# 健康检查脚本示例 (shell)
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health
# 返回 200 视为正常
```

## 5. 监控与告警

| 指标名称                 | 来源          | 告警阈值                   | 描述                     |
|--------------------------|---------------|----------------------------|--------------------------|
| `gateway_request_total`  | Prometheus    | 较基线上升 30%             | 总请求数                 |
| `gateway_http_4xx_total` | Prometheus    | 比例 > 10%                 | 客户端错误               |
| `gateway_http_5xx_total` | Prometheus    | 比例 > 1%                  | 服务端错误               |
| `gateway_latency_p99`    | Prometheus    | > 2000ms                   | p99 延迟                 |
| `rate_limit_blocked`     | 日志统计     