# Redis 集群搭建与高可用方案

| 文档版本 | 修改日期 | 修改人 | 修改内容 |
|---------|----------|--------|---------|
| V1.0 | 2024-03-15 | 李明 | 初始版本 |
| V1.1 | 2024-06-20 | 王强 | 新增故障恢复流程 |

**维护团队**：基础设施运维组  
**负责人**：王强  
**审批人**：张磊  

---

## 1. 概述

本文档描述 Redis 集群的搭建流程、配置参数及高可用保障方案。本集群用于支撑线上业务缓存、Session 共享及分布式锁场景，部署环境为 CentOS 7.9，Redis 版本 6.2.12。

## 2. 集群架构

我们采用 **Redis Cluster** 原生分片方案，结合 **Sentinel** 进行主从切换，实现数据分片与节点故障自动恢复。整体架构如下：

- 3 组主从节点（每组 1 主 1 从），共 6 个 Redis 实例
- 3 个 Sentinel 节点独立部署，监控主节点状态
- 每个 Redis 实例绑定独立端口，主节点端口 7000-7002，从节点端口 7003-7005

```
+-------------------+       +-------------------+       +-------------------+
|  Master-1 (7000)  |<----->|  Master-2 (7001)  |<----->|  Master-3 (7002)  |
|   Slave-1 (7003)  |       |   Slave-2 (7004)  |       |   Slave-3 (7005)  |
+-------------------+       +-------------------+       +-------------------+
         ^                          ^                          ^
         |                          |                          |
+-------------------+       +-------------------+       +-------------------+
|  Sentinel-1 (26379)|       |  Sentinel-2 (26380)|       |  Sentinel-3 (26381)|
+-------------------+       +-------------------+       +-------------------+
```

## 3. 环境准备

### 3.1 服务器规划

| 主机名 | IP 地址 | 角色 | 部署组件 |
|--------|---------|------|---------|
| redis-node1 | 192.168.1.101 | 主节点 1 + 从节点 3 | Redis, Sentinel |
| redis-node2 | 192.168.1.102 | 主节点 2 + 从节点 4 | Redis, Sentinel |
| redis-node3 | 192.168.1.103 | 主节点 3 + 从节点 5 | Redis, Sentinel |

### 3.2 系统调优

在所有节点执行以下配置：

```bash
# 修改系统限制
echo "vm.overcommit_memory = 1" >> /etc/sysctl.conf
sysctl -p

# 禁用 THP
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo 'echo never > /sys/kernel/mm/transparent_hugepage/enabled' >> /etc/rc.local
chmod +x /etc/rc.local

# 修改文件描述符限制
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf
```

## 4. Redis 集群搭建

### 4.1 安装 Redis

所有节点执行：

```bash
# 下载并编译 Redis 6.2.12
wget https://download.redis.io/releases/redis-6.2.12.tar.gz
tar -xzf redis-6.2.12.tar.gz
cd redis-6.2.12
make -j4
make install PREFIX=/usr/local/redis

# 创建数据目录
mkdir -p /data/redis/{7000,7001,7002,7003,7004,7005}
mkdir -p /var/log/redis
```

### 4.2 配置主节点实例

以 redis-node1 主节点（端口 7000）为例，创建 `/usr/local/redis/conf/redis-7000.conf`：

```conf
port 7000
daemonize yes
pidfile /var/run/redis/redis-7000.pid
logfile /var/log/redis/redis-7000.log
dir /data/redis/7000

# 集群配置
cluster-enabled yes
cluster-config-file nodes-7000.conf
cluster-node-timeout 15000
cluster-require-full-coverage no

# 持久化配置
appendonly yes
appendfsync everysec
save 900 1
save 300 10
save 60 10000

# 内存管理
maxmemory 4gb
maxmemory-policy allkeys-lru
```

其他主节点（7001, 7002）和从节点（7003-7005）的配置文件类似，只需修改端口号、日志路径和数据目录。

### 4.3 启动实例

在每个节点启动相应实例，以 redis-node1 为例：

```bash
# 启动主节点
/usr/local/redis/bin/redis-server /usr/local/redis/conf/redis-7000.conf
# 启动从节点
/usr/local/redis/bin/redis-server /usr/local/redis/conf/redis-7003.conf
```

### 4.4 创建集群

在任意节点（如 redis-node1）执行：

```bash
/usr/local/redis/bin/redis-cli --cluster create \
  192.168.1.101:7000 192.168.1.102:7001 192.168.1.103:7002 \
  192.168.1.101:7003 192.168.1.102:7004 192.168.1.103:7005 \
  --cluster-replicas 1
```

输入 `yes` 确认后，集群创建成功，输出类似：

```
>>> Performing hash slots allocation on 6 nodes...
Master[0] -> Slots 0 - 5460
Master[1] -> Slots 5461 - 10922
Master[2] -> Slots 10923 - 16383
Adding replica 192.168.1.101:7003 to 192.168.1.101:7000
Adding replica 192.168.1.102:7004 to 192.168.1.102:7001
Adding replica 192.168.1.103:7005 to 192.168.1.103:7002
```

### 4.5 验证集群

```bash
# 查看集群节点状态
/usr/local/redis/bin/redis-cli -c -h 192.168.1.101 -p 7000 cluster nodes

# 测试写入与读取
/usr/local/redis/bin/redis-cli -c -h 192.168.1.101 -p 7000 set test_key "hello"
/usr/local/redis/bin/redis-cli -c -h 192.168.1.102 -p 7001 get test_key
```

## 5. Sentinel 高可用配置

### 5.1 配置 Sentinel

在每个节点创建 Sentinel 配置，以 redis-node1 为例，文件 `/usr/local/redis/conf/sentinel-26379.conf`：

```conf
port 26379
daemonize yes
pidfile /var/run/redis/sentinel-26379.pid
logfile /var/log/redis/sentinel-26379.log
dir /data/redis

# 监控主节点
sentinel monitor mymaster 192.168.1.101 7000 2
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 30000
sentinel parallel-syncs mymaster 1

# 密码认证（如启用）
# sentinel auth-pass mymaster yourpassword
```

**注意**：`sentinel monitor` 中的 `2` 表示需要至少 2 个 Sentinel 同意才能判定主节点故障。

### 5.2 启动 Sentinel

所有节点执行：

```bash
/usr/local/redis/bin/redis-sentinel /usr/local/redis/conf/sentinel-26379.conf
```

### 5.3 验证 Sentinel

```bash
# 查看 Sentinel 状态
/usr/local/redis/bin/redis-cli -p 26379 sentinel master mymaster
/usr/local/redis/bin/redis-cli -p 26379 sentinel slaves mymaster
```

预期输出应显示 1 个主节点和 2 个从节点信息。

## 6. 故障模拟与恢复

### 6.1 模拟主节点宕机

```bash
# 在 redis-node1 上停止主节点
/usr/local/redis/bin/redis-cli -p 7000 SHUTDOWN NOSAVE
```

### 6.2 观察自动切换

检查 Sentinel 日志 `/var/log/redis/sentinel-26379.log`，应看到类似输出：

```
+sdown master mymaster 192.168.1.101 7000
+odown master mymaster 192.168.1.101 7000 #quorum 2/2
+switch-master mymaster 192.168