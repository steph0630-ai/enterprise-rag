# 日志采集系统 ELK 搭建与索引优化

**文档编号**: OPS-ELK-20231001  
**版本**: v2.1  
**编写人**: 张明（中间件运维组）  
**审核人**: 李强（SRE 负责人）  
**生效日期**: 2024-03-15  
**最后修订**: 2024-09-20  

---

## 1. 变更记录

| 版本 | 日期 | 修改内容 | 修改人 |
|------|------|----------|--------|
| v1.0 | 2023-10-01 | 初始版本 | 张明 |
| v2.0 | 2024-06-10 | 升级 Elasticsearch 7.17 → 8.11，调整索引生命周期策略 | 张明 |
| v2.1 | 2024-09-20 | 增加磁盘水位线配置、修复 Logstash 内存溢出问题 | 王磊 |

---

## 2. 系统架构概述

本 ELK 集群部署于内部 Kubernetes 集群（命名空间 `logging`），采用以下组件：

- **Elasticsearch 8.11.3**：3 节点热节点 + 2 节点温节点，数据分片 3 副本 2
- **Logstash 8.11.3**：4 个 Pod，每个 Pod 分配 4GB Heap，使用 pipeline 隔离
- **Kibana 8.11.3**：2 个 Pod，通过 Nginx 反向代理暴露
- **Filebeat 8.11.3**：DaemonSet 部署在每个 K8s 节点上，采集容器日志和系统日志

### 2.1 数据流路径

```
应用 Pod (stdout/stderr) 
  → Filebeat (DaemonSet) 
  → Kafka (topic: app-log, 3 partitions) 
  → Logstash (consumer group: logstash-group) 
  → Elasticsearch (index: app-log-{YYYY.MM.dd})
```

### 2.2 索引命名规范

| 日志类型 | 索引前缀 | 保留天数 | 冷存储天数 |
|----------|----------|----------|------------|
| 应用日志 | app-log-{日期} | 30 | 90 |
| 系统日志 | syslog-{日期} | 7 | 30 |
| 安全审计 | audit-{日期} | 180 | 365 |
| Nginx 访问日志 | nginx-access-{日期} | 14 | 60 |

---

## 3. 环境部署

### 3.1 Elasticsearch 集群配置

使用 Helm chart `elastic/elasticsearch` 部署，核心 values 文件如下：

```yaml
# es-values.yaml
clusterName: "prod-elk"
nodeGroup: "hot"
replicas: 3
minimumMasterNodes: 2
resources:
  requests:
    cpu: "4"
    memory: "16Gi"
  limits:
    cpu: "6"
    memory: "24Gi"
volumeClaimTemplate:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 1Ti
  storageClassName: "fast-ssd"
esConfig:
  elasticsearch.yml: |
    cluster.routing.allocation.disk.watermark.low: 85%
    cluster.routing.allocation.disk.watermark.high: 90%
    cluster.routing.allocation.disk.watermark.flood_stage: 95%
    index.number_of_shards: 3
    index.number_of_replicas: 2
    indices.memory.index_buffer_size: 15%
    thread_pool.write.queue_size: 500
    discovery.zen.minimum_master_nodes: 2
```

**部署命令**：
```bash
helm repo add elastic https://helm.elastic.co
helm upgrade --install es-hot elastic/elasticsearch -f es-values.yaml -n logging
```

### 3.2 Logstash 配置

pipeline 配置文件 `/usr/share/logstash/pipeline/app-log.conf`：

```ruby
input {
  kafka {
    bootstrap_servers => "kafka-cluster:9092"
    topics => ["app-log"]
    group_id => "logstash-group"
    consumer_threads => 4
    auto_offset_reset => "latest"
    codec => "json"
  }
}

filter {
  # 解析标准 JSON 格式的应用日志
  json {
    source => "message"
    target => "parsed"
  }
  
  # 添加 @timestamp 字段（如果原始日志中没有）
  if [@timestamp] {
    date {
      match => ["@timestamp", "ISO8601"]
      target => "@timestamp"
    }
  } else {
    ruby {
      code => 'event.set("@timestamp", event.get("time"))'
    }
  }

  # 使用 geoip 解析客户端 IP（仅对访问日志）
  if [type] == "nginx-access" {
    geoip {
      source => "[parsed][client_ip]"
      target => "geo"
    }
  }

  # 丢弃 debug 级别日志（减少存储）
  if [parsed][level] == "DEBUG" {
    drop {}
  }
}

output {
  elasticsearch {
    hosts => ["http://es-hot:9200"]
    user => "logstash_internal"
    password => "${ES_PASSWORD}"
    index => "app-log-%{+YYYY.MM.dd}"
    ilm_enabled => true
    ilm_rollover_alias => "app-log"
    ilm_policy => "app-log-policy"
    ilm_pattern => "{now/d}-000001"
    manage_template => true
    template_overwrite => true
  }
}
```

### 3.3 索引生命周期策略（ILM）

通过 Kibana Dev Tools 创建策略：

```json
PUT _ilm/policy/app-log-policy
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "50GB",
            "max_age": "1d"
          },
          "set_priority": {
            "priority": 100
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "forcemerge": {
            "max_num_segments": 1
          },
          "shrink": {
            "number_of_shards": 1
          },
          "allocate": {
            "number_of_replicas": 1,
            "require": {
              "data": "warm"
            }
          },
          "set_priority": {
            "priority": 50
          }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "allocate": {
            "number_of_replicas": 0,
            "require": {
              "data": "cold"
            }
          },
          "freeze": {},
          "set_priority": {
            "priority": 0
          }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

---

## 4. 索引优化策略

### 4.1 索引模板优化

```json
PUT _index_template/app-log-template
{
  "index_patterns": ["app-log-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 2,
      "index.refresh_interval": "30s",
      "index.translog.durability": "async",
      "index.translog.sync_interval": "30s",
      "index.search.slowlog.threshold.query.warn": "5s",
      "index.search.slowlog.threshold.fetch.warn": "2s"
    },
    "mappings": {
      "dynamic": "strict",
      "properties": {
        "@timestamp": { "type": "date" },
        "level": { "type": "keyword" },
        "logger_name": { "type": "keyword" },
        "message": { 
          "type": "text",
          "analyzer": "standard",
          "fields": {
            "keyword": { "type": "keyword" }
          }
        },
        "thread_name": { "type": "keyword" },
        "service_name": { "type": "keyword" },
        "trace_id": { "type": "keyword" },
        "parsed": {
          "dynamic": true,
          "properties": {
            "client_ip": { "type": "ip" },
            "request_method": { "type": "keyword" },
            "response_code": { "type": "integer" },
            "duration_ms": { "type": "float" }
          }
        }
      }
    }
  }
}
```

### 4.2 查询优化最佳实践

1. **避免全字段搜索**：使用 `fields` 指定搜索字段，例如 `message: "ERROR"` 而非 `"ERROR"`
2. **使用 filter context**：对于精确匹配（如 `level: "ERROR"`），使用 `filter` 而非 `query`，可缓存结果
3. **合理设置 shard 数量**：每个 shard 大小控制在 