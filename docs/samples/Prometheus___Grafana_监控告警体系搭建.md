# Prometheus + Grafana 监控告警体系搭建运维手册

**文档编号**: OPS-MON-002  
**版本**: v2.3  
**最后更新**: 2025-03-18  
**负责人**: 张明（运维组）  
**审批人**: 李强（基础架构负责人）  

---

## 变更记录

| 版本 | 变更日期 | 变更内容 | 变更人 |
|------|----------|----------|--------|
| v1.0 | 2024-06-15 | 初始版本，Prometheus 2.45 + Grafana 10.1 | 张明 |
| v2.0 | 2024-12-20 | 新增告警规则、联邦集群配置，升级至 Prometheus 2.53 | 王磊 |
| v2.3 | 2025-03-18 | 修复 Alertmanager 路由配置问题，增加 Node Exporter 安全配置 | 张明 |

---

## 1. 概述

本运维手册描述公司生产环境、预发布环境（Staging）中 Prometheus 与 Grafana 监控告警体系的完整搭建、配置与运维流程。体系覆盖所有 Kubernetes 集群节点、关键中间件（MySQL、Redis、Kafka）及业务应用（HTTP 端点、gRPC 服务）的指标采集、存储、可视化与告警通知。

---

## 2. 架构说明

### 2.1 总体架构

采用 **Prometheus 联邦集群** 模式，分为中心控制层与数据采集层：

- **中心 Prometheus**：部署在 `ap-southeast-1` 区域的主集群，作为统一查询入口，存储长期指标（保留 90 天），配置 Alertmanager 发送告警。
- **边缘 Prometheus**：每个 Kubernetes 集群或独立物理机房部署一个边缘实例，负责本地采集与短期存储（保留 30 天），并通过 `remote_write` 向中心写入聚合指标。
- **Grafana**：部署在中心，通过多个 Prometheus 数据源展示跨区域大盘。

### 2.2 组件版本

| 组件 | 版本 | 部署方式 |
|------|------|----------|
| Prometheus Server | 2.53.1 | Docker / Helm |
| Node Exporter | 1.7.0 | DaemonSet (K8s) |
| Alertmanager | 0.27.0 | Docker / Helm |
| Grafana | 10.4.3 | Docker / Helm |
| kube-state-metrics | 2.12.0 | Deployment (K8s) |

---

## 3. 环境要求

- 操作系统：Ubuntu 22.04 LTS / CentOS 7.9+
- Docker Engine 24.0+ 或 containerd 1.7+（用于 K8s 节点）
- 防火墙开放端口：
  - Prometheus: `9090`（HTTP）、`9091`（Alertmanager）
  - Node Exporter: `9100`
  - Grafana: `3000`（HTTPS 需通过反向代理）
- 磁盘空间：边缘节点至少 100GB 用于 Prometheus WAL 与 TSDB 块，中心节点至少 500GB（建议挂载 SSD）

---

## 4. 部署步骤

### 4.1 安装 Prometheus Server

#### 方法一：Docker 部署（单节点）

```bash
# 创建配置目录
mkdir -p /etc/prometheus /var/lib/prometheus

# 下载默认配置文件
wget -O /etc/prometheus/prometheus.yml https://raw.githubusercontent.com/prometheus/prometheus/v2.53.1/config/prometheus.yml

# 启动容器
docker run -d \
  --name prometheus \
  --restart=always \
  -p 9090:9090 \
  -v /etc/prometheus:/etc/prometheus \
  -v /var/lib/prometheus:/prometheus \
  prom/prometheus:v2.53.1 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.retention.time=30d \
  --web.enable-lifecycle
```

#### 方法二：Helm 部署（Kubernetes 集群）

```bash
# 添加 Helm 仓库
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# 安装 kube-prometheus-stack（包含 Prometheus、Alertmanager、Grafana 及 kube-state-metrics）
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f values.yaml
```

**示例 `values.yaml` 关键配置段：**

```yaml
prometheus:
  prometheusSpec:
    retention: 30d
    retentionSize: 50GB
    resources:
      requests:
        memory: 4Gi
        cpu: 2
      limits:
        memory: 8Gi
        cpu: 4
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: fast-ssd
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 200Gi
alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
      smtp_smarthost: 'smtp.company.com:587'
      smtp_from: 'alert@company.com'
      smtp_auth_username: 'alert@company.com'
      smtp_auth_password: 'your-smtp-password'
```

### 4.2 部署 Node Exporter

在每台 K8s 节点上以 DaemonSet 方式运行：

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      hostNetwork: true
      hostPID: true
      containers:
      - name: node-exporter
        image: prom/node-exporter:v1.7.0
        args:
        - --path.rootfs=/host
        - --web.listen-address=:9100
        - --no-collector.wifi
        - --collector.filesystem.ignored-mount-points=^/(sys|proc|dev|host|etc)($|/)
        ports:
        - containerPort: 9100
          hostPort: 9100
        volumeMounts:
        - name: root
          mountPath: /host
          readOnly: true
      volumes:
      - name: root
        hostPath:
          path: /
```

**安全加固**：添加 `--web.config.file` 参数启用 HTTP Basic Auth，配置文件 `/etc/node_exporter/config.yml`：

```yaml
basic_auth_users:
  prometheus: $2y$10$... # bcrypt 加密密码
```

### 4.3 配置 Prometheus 抓取目标

在 `/etc/prometheus/prometheus.yml` 中添加以下 job：

```yaml
scrape_configs:
  # 自监控
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # K8s 节点监控（Node Exporter）
  - job_name: 'node'
    scrape_interval: 30s
    static_configs:
      - targets:
        - '10.0.1.10:9100'
        - '10.0.1.11:9100'
        - '10.0.1.12:9100'
    basic_auth:
      username: prometheus
      password_file: /etc/prometheus/node_auth.txt

  # 中间件（MySQL）
  - job_name: 'mysql'
    static_configs:
      - targets: ['10.0.2.50:9104']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '(.+):9104'
        replacement: '$1'

  # 业务应用（HTTP 端点）
  - job_name: 'business-api'
    metrics_path: '/actuator/prometheus'
    scheme: https
    tls_config:
      insecure_skip_verify: false
    static_configs:
      - targets:
        - 'api.internal.company.com:443'
```

### 4.4 配置告警规则

创建文件 `/etc/prometheus/rules/node_alerts.yml`：

```yaml
groups:
- name: node_alerts
  interval: 30s
  rules:
  - alert: NodeHighCPUUsage
    expr: (100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)) > 80
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Node {{ $labels.instance }} CPU usage > 80%"
      description: "CPU usage on node {{ $labels.instance }} is at {{ $value }}% for 5 minutes."

  - alert: NodeDiskAlmostFull
    expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint