# 缓存使用规范：Redis 缓存策略与击穿防护

**文档编号**：TECH-SPEC-2024-012  
**版本**：v2.3  
**最后更新**：2024-07-15  
**负责人**：张伟（基础架构组）  
**审批人**：李明（技术VP）

---

## 变更记录

| 版本 | 日期       | 修改人 | 变更内容                     |
|------|------------|--------|------------------------------|
| v1.0 | 2023-09-10 | 张伟   | 初始版本                     |
| v2.0 | 2024-03-01 | 张伟   | 新增缓存击穿防护策略         |
| v2.1 | 2024-05-20 | 王芳   | 更新过期策略参数             |
| v2.2 | 2024-06-10 | 赵强   | 增加多级缓存架构示意图       |
| v2.3 | 2024-07-15 | 张伟   | 修订互斥锁超时时间，增加监控指标 |

---

## 1. 概述

本文档规定了基于 Redis 的缓存使用规范，涵盖缓存策略选择、过期时间配置、内存淘汰机制以及缓存击穿、穿透、雪崩的防护方案。所有涉及缓存操作的新服务或现有服务改造，必须遵循此规范。

### 1.1 适用范围

- 所有使用 Redis 作为缓存层的微服务
- 涉及热点数据、高并发读的业务场景
- 缓存与数据库之间的数据一致性处理

---

## 2. 缓存策略

### 2.1 缓存粒度

| 粒度   | 适用场景                 | 示例                         |
|--------|--------------------------|------------------------------|
| 对象级 | 单个实体频繁查询         | 用户信息、订单详情           |
| 列表级 | 分页列表、排行榜         | 最近订单、商品榜单           |
| 聚合级 | 统计数据、汇总结果       | 日活用户数、累计销售额       |

**规范要求**：同一业务场景内，优先使用对象级缓存，避免大 key（>10 KB）导致网络传输和内存压力。

### 2.2 过期时间配置

| 数据类型         | 默认 TTL | 最大 TTL | 说明                                 |
|------------------|----------|----------|--------------------------------------|
| 用户 Session     | 30 min   | 2 h      | 使用 EXPIRE 命令动态刷新             |
| 商品详情         | 10 min   | 1 h      | 结合数据库更新时间动态调整           |
| 配置信息         | 1 h      | 24 h     | 配置变更时主动失效                   |
| 排行榜数据       | 5 min    | 30 min   | 实时性要求高，短 TTL                 |
| 聚合统计         | 15 min   | 2 h      | 允许最终一致性                       |

**示例配置（Spring Boot + Lettuce）**：

```yaml
spring:
  redis:
    timeout: 2000ms
    lettuce:
      pool:
        max-active: 8
        max-idle: 4
        min-idle: 2
    cache:
      redis:
        time-to-live: 600000  # 默认10分钟
        cache-null-values: false
```

### 2.3 内存淘汰策略

生产环境 Redis 实例统一配置：

```bash
# redis.conf
maxmemory 4gb
maxmemory-policy allkeys-lru
```

- **allkeys-lru**：适用于大部分业务场景，优先淘汰最近最少使用的 key
- **volatile-lru**：仅对设置了过期时间的 key 生效（仅限特定场景，需申请审批）

**禁止使用**：`noeviction`（会导致写入失败）和 `allkeys-random`（不可控）。

---

## 3. 缓存击穿防护

### 3.1 问题定义

缓存击穿指热点 key 在过期瞬间，大量请求同时穿透到数据库，导致数据库压力激增。

### 3.2 防护方案

#### 方案一：互斥锁（推荐）

使用 Redis 分布式锁（基于 SETNX）控制只有一个请求回源加载数据。

**Java 实现示例**：

```java
public String getWithMutex(String key) {
    String value = redisTemplate.opsForValue().get(key);
    if (value != null) {
        return value;
    }
    
    // 获取分布式锁
    String lockKey = "lock:" + key;
    Boolean lock = redisTemplate.opsForValue()
        .setIfAbsent(lockKey, "1", 3, TimeUnit.SECONDS);
    
    if (Boolean.TRUE.equals(lock)) {
        try {
            // 双重检查，防止重复加载
            value = redisTemplate.opsForValue().get(key);
            if (value != null) {
                return value;
            }
            // 从数据库加载
            value = loadFromDatabase(key);
            // 设置缓存，TTL 随机增加 1-5 秒，防止同时过期
            int ttl = 600 + new Random().nextInt(300);
            redisTemplate.opsForValue().set(key, value, ttl, TimeUnit.SECONDS);
            return value;
        } finally {
            redisTemplate.delete(lockKey);  // 释放锁
        }
    } else {
        // 未获取到锁，等待后重试
        Thread.sleep(50);
        return getWithMutex(key);  // 递归重试
    }
}
```

**关键参数**：
- 锁超时时间：3 秒（根据数据库查询耗时调整）
- 等待重试间隔：50 ms
- 最大重试次数：3 次（防止死循环）

#### 方案二：逻辑过期（备选）

在 value 中存储逻辑过期时间，异步刷新缓存。

```java
public class CacheItem<T> {
    private T data;
    private long expireTime;  // 逻辑过期时间戳（毫秒）
}
```

**使用场景**：对实时性要求较低的热点数据，如首页推荐列表。

### 3.3 缓存穿透防护

对于不存在的数据，缓存空值（null placeholder）并设置短 TTL：

```java
// 缓存空值，TTL 60秒
redisTemplate.opsForValue()
    .set(key, "NULL", 60, TimeUnit.SECONDS);
```

### 3.4 缓存雪崩防护

1. **过期时间随机化**：基础 TTL + 随机偏移（±30%）
2. **多级缓存**：本地缓存（Caffeine）+ Redis 缓存
3. **限流降级**：使用 Sentinel 对回源数据库操作限流

---

## 4. 多级缓存架构

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  客户端      │─────▶│  本地缓存     │─────▶│  Redis 集群  │
│  (App/Web)   │      │  (Caffeine)  │      │  (6节点)     │
└──────────────┘      └──────────────┘      └──────────────┘
                                                │
                                                ▼
                                          ┌──────────────┐
                                          │  数据库       │
                                          │  (MySQL RDS) │
                                          └──────────────┘
```

**Caffeine 配置**：

```java
Cache<String, Object> localCache = Caffeine.newBuilder()
    .maximumSize(10000)
    .expireAfterWrite(5, TimeUnit.MINUTES)
    .recordStats()
    .build();
```

---

## 5. 监控与告警

### 5.1 关键指标

| 指标名称                      | 采集方式              | 告警阈值         |
|-------------------------------|-----------------------|------------------|
| Redis 内存使用率              | Prometheus + redis_exporter | > 80%           |
| 缓存命中率                    | 业务埋点              | < 85%            |
| 互斥锁等待时间（P99）         | 业务日志              | > 500 ms         |
| 数据库回源 QPS                | 数据库监控            | > 2000 QPS       |

### 5.2 监控命令

```bash
# 查看 Redis 内存使用情况
redis-cli -h prod-redis-001.example.com -p 6379 INFO memory

# 查看缓存命中率（需启用统计）
redis-cli -h prod-redis-001.example.com -p 6379 INFO stats
```

---

## 6. 常见问题排查

### 6.1 缓存不一致

**现象**：数据库已更新，但缓存仍是旧数据。  
**处理流程**：
1. 检查是否使用了”先删缓存，再更新数据库”的模式
2. 推荐使用”延迟双删”策略：更新数据库前删除缓存，延迟 200ms 后再次删除
3. 对于一致性要求高的场景，使用 Canal 监听 binlog 异步刷新缓存

### 6.2 大 Key 问题

**排查命令**：

```bash
# 查找大 key（需在低峰期执行）
redis-cli --bigkeys

# 分析单个 key