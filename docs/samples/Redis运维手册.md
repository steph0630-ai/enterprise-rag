# Redis 运维手册

## 服务信息

- **集群地址**: redis-cluster.internal.company.com:6379
- **节点数**: 6 个节点（3 主 3 从）
- **内存上限**: 16GB / 节点
- **淘汰策略**: allkeys-lru
- **负责人**: 李四

## 常见操作

### 查看集群状态

```bash
redis-cli -h redis-cluster.internal.company.com -p 6379 CLUSTER INFO
redis-cli -h redis-cluster.internal.company.com -p 6379 CLUSTER NODES
```

### 查看内存使用

```bash
redis-cli -h redis-cluster.internal.company.com -p 6379 INFO memory | grep used_memory_human
```

### 手动故障转移

```bash
redis-cli -h redis-cluster.internal.company.com -p 6379 CLUSTER FAILOVER
```

## 故障处理

### 问题1：内存使用超过 80%

**症状**: 监控告警，Redis 内存使用超过阈值。部分 key 被提前淘汰，缓存命中率下降。

**排查步骤**:
1. 检查大 key：`redis-cli --bigkeys`
2. 检查过期 key 数量：`redis-cli INFO stats | grep expired_keys`
3. 分析 key 分布：`redis-cli INFO keyspace`

**解决方案**:
1. 临时方案：手动扩容，在控制台将内存上限调整为 20GB
2. 长期方案：优化业务代码，对大 value 进行压缩，或对无过期时间的 key 设置 TTL

### 问题2：主从同步延迟

**症状**: 从节点数据落后于主节点，读取到过期数据。

**排查步骤**:
1. 检查复制偏移量：`redis-cli INFO replication | grep master_repl_offset`
2. 检查网络延迟：`redis-cli --latency -h <master_ip>`
3. 检查主节点负载：`redis-cli INFO stats | grep instantaneous_ops_per_sec`

**解决方案**:
1. 如果 OPS 超过 10 万，考虑对业务进行读写分离
2. 如果是网络问题，联系基础架构组检查跨机房专线

## 配置参数

| 参数 | 值 | 说明 |
|---|---|---|
| maxmemory | 16GB | 单节点最大内存 |
| maxmemory-policy | allkeys-lru | 内存淘汰策略 |
| timeout | 300 | 客户端空闲超时（秒） |
| maxclients | 10000 | 最大客户端连接数 |
| tcp-keepalive | 60 | TCP 保活时间（秒） |
| slowlog-log-slower-than | 10000 | 慢查询阈值（微秒） |
