# 消息队列使用规范 (Kafka/RabbitMQ 选型与配置)

| 文档编号 | TECH-SPEC-MQ-2024-001 |
|---------|----------------------|
| 版本号   | v2.3                 |
| 最后更新 | 2024-07-15           |
| 负责人   | 中间件团队 - 张工    |
| 审批人   | 架构委员会           |

---

## 1. 变更记录

| 版本 | 日期       | 变更内容                                   | 作者   |
|------|------------|--------------------------------------------|--------|
| v1.0 | 2023-05-10 | 初版制定，包含基础选型与配置规范           | 李工   |
| v2.0 | 2024-01-20 | 增加死信策略、监控指标与扩容方案           | 王工   |
| v2.1 | 2024-04-08 | 修正Kafka分区数计算公式，补充RabbitMQ队列绑定规则 | 赵工   |
| v2.2 | 2024-06-01 | 增加多数据中心部署要求，更新安全配置       | 张工   |
| v2.3 | 2024-07-15 | 增加消息压缩配置与性能调优建议             | 张工   |

---

## 2. 选型原则

### 2.1 核心判断矩阵

| 场景特征                          | 推荐中间件 | 理由                                                                 |
|-----------------------------------|-----------|----------------------------------------------------------------------|
| 高吞吐、日志收集、流式处理         | Apache Kafka | 吞吐量可达百万级/秒，天然支持分区并行与持久化                        |
| 复杂路由、事务消息、低延迟<10ms    | RabbitMQ    | 灵活的Exchange/Binding机制，支持Confirm/Ack模式，延迟稳定在1-5ms    |
| 需要严格顺序保证的支付/订单场景    | Kafka       | 分区内严格有序，但需注意分区数设计                                   |
| 需要延迟队列、优先级队列           | RabbitMQ    | 原生支持TTL与DLX，可轻松实现延迟消息                                 |
| 与现有Spring Cloud体系深度集成     | RabbitMQ    | Spring AMQP/Cloud Stream支持更成熟                                   |

### 2.2 禁止使用的场景

- **RPC调用**：消息队列不应替代RPC或HTTP接口进行同步调用，避免引入额外的延迟与复杂度。
- **数据库替代**：禁止将MQ作为持久存储引擎使用，消息应设计为可丢失或可重放。
- **跨环境透传**：禁止将生产环境消息直接转发至测试环境，必须经过脱敏与数据过滤。

---

## 3. Kafka 配置规范

### 3.1 分区与副本设计

```yaml
# 分区数计算公式（适用于业务主题）
partition_count = max(consumers * 2, throughput_goal_MBps / 10)

# 副本因子
replication_factor = 3  # 生产环境最低要求
min_insync_replicas = 2
```

**示例**：某订单主题预期吞吐量 500 MB/s，消费者组有 8 个实例  
`partition_count = max(8*2, 500/10) = max(16, 50) = 50`

### 3.2 关键配置参数

```properties
# server.properties
# 日志保留策略
log.retention.hours=72
log.retention.bytes=107374182400        # 100GB
log.segment.bytes=1073741824            # 1GB
log.cleanup.policy=delete

# 性能调优
num.network.threads=8
num.io.threads=16
socket.request.max.bytes=104857600      # 100MB
message.max.bytes=10485760              # 10MB
compression.type=snappy                 # 启用压缩，降低网络IO

# 消费者配置
offsets.topic.replication.factor=3
transaction.state.log.replication.factor=3
transaction.state.log.min.isr=2
```

### 3.3 生产者配置

```java
// Java Producer 示例
Properties props = new Properties();
props.put("bootstrap.servers", "kafka-01:9092,kafka-02:9092,kafka-03:9092");
props.put("acks", "all");                          // 等待所有副本确认
props.put("retries", 3);
props.put("max.in.flight.requests.per.connection", 1); // 保证分区内顺序
props.put("linger.ms", 5);                         // 批量发送，减少请求数
props.put("batch.size", 65536);                    // 64KB
props.put("compression.type", "snappy");
```

### 3.4 消费者配置

```java
// 消费者组配置
props.put("group.id", "order-service-group");
props.put("enable.auto.commit", false);            // 手动提交偏移量
props.put("max.poll.records", 500);
props.put("session.timeout.ms", 30000);
props.put("heartbeat.interval.ms", 10000);
props.put("isolation.level", "read_committed");    // 避免读取未提交事务消息
```

---

## 4. RabbitMQ 配置规范

### 4.1 虚拟主机与权限

```bash
# 创建虚拟主机
rabbitmqctl add_vhost /production_order
rabbitmqctl add_vhost /production_log

# 设置权限（遵循最小权限原则）
rabbitmqctl set_permissions -p /production_order order_service ".*" ".*" "(amq\.gen.*|order\.*)"
```

### 4.2 Exchange 与 Queue 命名规范

| 元素      | 命名规则                    | 示例                             |
|-----------|----------------------------|----------------------------------|
| Exchange  | `{领域}.{类型}.{功能}`     | `order.direct.create`            |
| Queue     | `{服务名}.{业务}.{版本}`   | `order.payment.v3`               |
| RoutingKey| `{源}.{动作}.{目标}`       | `order.created.notify`           |

### 4.3 关键配置参数

```yaml
# rabbitmq.conf
# 连接与心跳
heartbeat = 30
connection_timeout = 60000
channel_max = 2048

# 内存与磁盘限制
vm_memory_high_watermark = 0.7
vm_memory_high_watermark_paging_ratio = 0.8
disk_free_limit = 5GB

# 消息确认与持久化
queue_master_locator = min-masters
hipe_compile = true
```

### 4.4 死信队列配置

```python
# 使用Python pika示例声明死信队列
channel.exchange_declare(
    exchange='order.dlx',
    exchange_type='direct',
    durable=True
)

channel.queue_declare(
    queue='order.payment.dlx',
    durable=True,
    arguments={
        'x-message-ttl': 86400000,  # 24小时后丢弃
        'x-dead-letter-exchange': 'order.retry',
        'x-dead-letter-routing-key': 'retry.payment'
    }
)
```

---

## 5. 监控与告警

### 5.1 核心监控指标

| 指标                    | 警告阈值          | 严重阈值          | 中间件    |
|------------------------|-------------------|-------------------|-----------|
| 消费者延迟(lag)        | > 1000条          | > 10000条         | Kafka     |
| 未确认消息数           | > 5000条          | > 50000条         | RabbitMQ |
| 磁盘使用率             | > 75%             | > 85%             | 通用      |
| 网络吞吐量             | > 80%带宽         | > 95%带宽         | 通用      |
| RabbitMQ 连接数        | > 500             | > 1000            | RabbitMQ |

### 5.2 告警配置示例

```yaml
# Prometheus Alertmanager 配置示例
groups:
  - name: mq_alerts
    rules:
      - alert: KafkaConsumerLagHigh
        expr: kafka_consumer_lag > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Consumer {{ $labels.group }} lag is {{ $value }}"

      - alert: RabbitMQUnackedMessages
        expr: rabbitmq_queue_messages_unacked > 5000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Queue {{ $labels.queue }} has {{ $value }} unacked messages"
```

---

## 6. 多数据中心部署要求

### 6.1 Kafka 跨数据中心

```
数据中心A (主)
  ├── broker-01
  ├── broker-02
  └── broker-03

数据中心B (备)
  ├── broker-04
  ├── broker-05
  └── broker-06

MirrorMaker2 同步方向: A -> B
同步延迟目标: < 2秒
```

### 6.2