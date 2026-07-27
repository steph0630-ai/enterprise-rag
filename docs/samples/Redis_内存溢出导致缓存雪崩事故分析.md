# Redis 内存溢出导致缓存雪崩事故分析

| 文档编号 | FR-2024-0032 |
|---------|------------|
| 版本号 | 1.2 |
| 编写人 | 张伟（SRE团队） |
| 审核人 | 李明（基础架构负责人） |
| 创建日期 | 2024-03-15 |
| 最后更新 | 2024-03-20 |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|---------|--------|
| 1.0 | 2024-03-15 | 初稿 | 张伟 |
| 1.1 | 2024-03-17 | 补充根因分析和改进措施 | 张伟 |
| 1.2 | 2024-03-20 | 增加自动化恢复脚本 | 李明 |

---

## 1. 事故概述

### 1.1 事故时间
- **开始时间**：2024-03-14 14:23 CST
- **结束时间**：2024-03-14 14:58 CST
- **持续时间**：35分钟

### 1.2 影响范围
- **服务影响**：用户订单查询、商品详情、推荐系统完全不可用
- **影响用户**：约120万在线用户
- **业务损失**：直接订单损失约230万元，用户体验严重下降

### 1.3 严重等级
**P0**（最高优先级事故）

---

## 2. 架构背景

### 2.1 缓存架构

系统采用 Redis Cluster 作为分布式缓存层，部署拓扑如下：

```
[应用层] → [Redis Cluster (6 nodes)] → [MySQL Primary-Replica]

Redis Cluster 节点配置：
- 节点数：6（3主3从）
- 内存配置：每个节点 32GB (maxmemory)
- 持久化策略：AOF + RDB 混合模式
- 淘汰策略：allkeys-lru
```

### 2.2 流量模型

- 正常 QPS：约 80,000
- 缓存命中率：95% 以上
- 数据过期时间：热点数据 30 分钟，普通数据 10 分钟

---

## 3. 事故时间线

| 时间 (CST) | 事件描述 | 状态 |
|------------|---------|------|
| 14:23:00 | 监控告警：Redis Cluster 节点3内存使用率超过95% | 告警触发 |
| 14:23:45 | 节点3触发 OOM，被操作系统 kill，导致主节点切换 | 宕机 |
| 14:24:10 | 剩余5个节点因客户端重连压力激增，内存使用率飙升至98% | 连锁反应 |
| 14:24:30 | 5个节点陆续 OOM，Redis Cluster 整体不可用 | 集群崩溃 |
| 14:25:00 | 大量请求穿透至 MySQL，数据库连接池瞬间耗尽，查询超时 | 雪崩 |
| 14:30:00 | SRE 团队介入，手动重启 Redis 节点 | 恢复开始 |
| 14:45:00 | Redis Cluster 重建完成，但缓存全部为空 | 缓存冷启动 |
| 14:55:00 | 预热脚本执行，缓存逐步填充 | 恢复中 |
| 14:58:00 | 缓存命中率恢复至85%，服务恢复正常 | 完全恢复 |

---

## 4. 根因分析

### 4.1 直接原因

**内存溢出触发点**：在 14:20-14:23 期间，推荐系统发布了一个新版本（v2.8.1），该版本引入了以下有问题的逻辑：

```java
// 问题代码示例 - RecommendService.java v2.8.1
public void cacheUserRecommendations(String userId, List<Product> products) {
    String key = "rec:user:" + userId + ":detail";
    
    // 问题1：直接将全量商品列表缓存，未做分页限制
    redisTemplate.opsForValue().set(key, products, 30, TimeUnit.MINUTES);
    
    // 问题2：同时缓存了多个冗余维度的数据
    for (Product product : products) {
        redisTemplate.opsForValue().set("rec:product:" + product.getId(), product, 30, TimeUnit.MINUTES);
        redisTemplate.opsForValue().set("rec:category:" + product.getCategoryId(), product, 30, TimeUnit.MINUTES);
    }
}
```

该代码导致：
- 每个用户的推荐列表缓存从平均 200KB 膨胀到 5MB
- 单个用户产生的缓存量为 5MB + 5MB * 200 = 约 1GB
- 并发用户数 1000+，瞬间写入量超过 1TB

### 4.2 根本原因

| 问题类型 | 具体原因 | 相关责任方 |
|---------|---------|-----------|
| 代码缺陷 | 未对缓存数据大小做限制，缺乏熔断机制 | 推荐系统团队 |
| 容量规划 | Redis 内存配置未考虑极端数据膨胀场景 | SRE 团队 |
| 监控缺失 | 未设置缓存 key 大小监控和单节点内存增长告警 | 监控团队 |
| 测试不足 | 新版本未进行压力测试和容量测试 | QA 团队 |
| 应急流程 | 缺乏自动化恢复脚本，依赖手动操作 | SRE 团队 |

### 4.3 雪崩传导机制

```
单个节点 OOM
    ↓
主节点切换，客户端重连
    ↓
重连请求导致其他节点负载飙升
    ↓
多节点连锁 OOM
    ↓
集群完全不可用
    ↓
请求全部穿透到数据库
    ↓
数据库连接池耗尽（最大连接数200）
    ↓
数据库查询队列堆积，响应超时
    ↓
上游服务因等待超时导致线程池耗尽
    ↓
服务全面不可用
```

---

## 5. 改进措施

### 5.1 短期措施（24小时内完成）

1. **配置限制**：在 Redis 配置中增加 maxmemory-policy 为 allkeys-lru，并设置单 key 大小上限

```bash
# redis.conf 配置修改
maxmemory 32gb
maxmemory-policy allkeys-lru
# 新增配置
maxmemory-samples 10
# 客户端限制
client-output-buffer-limit normal 0 0 0
client-output-buffer-limit slave 256mb 64mb 60
client-output-buffer-limit pubsub 32mb 8mb 60
```

2. **代码修复**：紧急回滚推荐系统至 v2.8.0，并修复缓存逻辑

```java
// 修复后的代码 - RecommendService.java v2.8.2
public void cacheUserRecommendations(String userId, List<Product> products) {
    // 限制缓存数据量
    if (products.size() > 50) {
        products = products.subList(0, 50);
    }
    
    String key = "rec:user:" + userId + ":detail";
    
    // 序列化前检查数据大小
    byte[] data = serialize(products);
    if (data.length > 1024 * 1024) { // 1MB 限制
        log.warn("Cache data too large for user: {}, size: {} bytes", userId, data.length);
        return;
    }
    
    redisTemplate.opsForValue().set(key, products, 30, TimeUnit.MINUTES);
}
```

### 5.2 中期措施（1周内完成）

1. **监控告警优化**

```yaml
# prometheus 告警规则
groups:
  - name: redis_alerts
    rules:
      - alert: RedisMemoryUsageHigh
        expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.8
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Redis 内存使用率超过80%"
      
      - alert: RedisKeySizeAnomaly
        expr: redis_key_size_bytes > 1048576
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Redis 单 key 大小超过1MB"
```

2. **容量规划升级**
   - Redis 节点内存从 32GB 升级至 64GB
   - 集群节点从 6 个扩容至 12 个
   - 增加独立缓存集群隔离不同业务（用户缓存、商品缓存、推荐缓存）

### 5.3 长期措施（1个月内完成）

1. **自动化恢复脚本**

```bash
#!/bin/bash
# redis_auto_recovery.sh - 自动恢复 Redis 集群

# 配置
CLUSTER_NODES=("redis-01:6379" "redis-02:6379" "redis-03:6379" "redis-04:6379" "redis-05:6379" "redis-06:6379")
LOG_FILE="/var/log/redis_recovery.log"

recover_node() {
    local node=$1
    echo "[$(date)] Starting recovery for node: $node" >> $LOG_FILE
    
    # 1. 检查节点状态
