# Kubernetes Pod 调度策略与资源限制配置

**文档编号**: OPS-K8S-2024-005  
**版本**: v2.1  
**最后更新**: 2024-09-20  
**负责人**: 张伟（基础架构组）  
**审批人**: 李明（技术总监）

---

## 1. 文档概述

本文档详细描述了企业内部 Kubernetes 集群中 Pod 的调度策略、资源限制（Resource Quotas）、服务质量（QoS）等级配置以及常见问题处理。适用对象为平台运维工程师、SRE 团队及有权限部署应用的开发人员。

**参考标准**: Kubernetes v1.28+，CNCF 最佳实践 v1.0。

---

## 2. 变更记录

| 版本 | 日期 | 修改人 | 变更内容 |
|------|------|--------|----------|
| v1.0 | 2024-01-15 | 张伟 | 初稿创建 |
| v2.0 | 2024-06-10 | 王芳 | 增加Pod拓扑分布约束策略 |
| v2.1 | 2024-09-20 | 张伟 | 更新资源限制计算公式，新增GPU调度说明 |

---

## 3. Pod 调度策略

### 3.1 节点选择器 (nodeSelector)

用于将 Pod 调度到带有特定标签的节点。适用于简单场景。

**示例 YAML**：
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: database-pod
  labels:
    app: mysql
spec:
  nodeSelector:
    disktype: ssd
    tier: database
  containers:
  - name: mysql
    image: mysql:8.0
```

**说明**：确保目标节点具有标签 `disktype=ssd` 和 `tier=database`。

### 3.2 节点亲和性 (Node Affinity)

提供更灵活的调度控制，支持硬性要求（required）和软性偏好（preferred）。

**硬性要求示例**（必须调度到GPU节点）：
```yaml
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: nvidia.com/gpu
            operator: Exists
```

**软性偏好示例**（优先调度到低延迟节点）：
```yaml
spec:
  affinity:
    nodeAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 80
        preference:
          matchExpressions:
          - key: latency-tier
            operator: In
            values:
            - "low"
```

### 3.3 Pod 亲和性与反亲和性 (Pod Affinity / Anti-Affinity)

控制 Pod 之间的调度关系。

**Pod 反亲和性示例**（避免同一服务副本调度到同一节点）：
```yaml
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: app
            operator: In
            values:
            - web-server
        topologyKey: "kubernetes.io/hostname"
```

**Pod 亲和性示例**（将缓存服务调度到同一可用区）：
```yaml
spec:
  affinity:
    podAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
            - key: app
              operator: In
              values:
              - redis-cache
          topologyKey: "topology.kubernetes.io/zone"
```

### 3.4 拓扑分布约束 (Topology Spread Constraints)

确保 Pod 在集群内均匀分布，避免单点故障。

**示例**（将副本分布在3个可用区）：
```yaml
spec:
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app: web-server
```

**参数说明**：
- `maxSkew`: 最大不均衡度（此处为1，即任意两个zone的Pod数差不超过1）
- `topologyKey`: 节点标签键（通常为 `kubernetes.io/hostname` 或 `topology.kubernetes.io/zone`）
- `whenUnsatisfiable`: 可选 `DoNotSchedule`（硬性约束）或 `ScheduleAnyway`（软性约束）

---

## 4. 资源限制配置

### 4.1 基本资源单位

| 资源类型 | 单位 | 示例 |
|----------|------|------|
| CPU | millicores (m) | 500m = 0.5 核 |
| 内存 | bytes (Mi, Gi) | 2Gi = 2048 MiB |
| 临时存储 | bytes | 10Gi |
| 扩展资源 | 自定义 | nvidia.com/gpu: 1 |

### 4.2 requests 与 limits 配置

**生产环境推荐配置公式**：
- `requests` = 基线负载 + 10% 缓冲
- `limits` = 峰值负载 × 1.2（内存）或 1.5（CPU）

**示例 Pod**：
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: payment-service
  namespace: production
spec:
  containers:
  - name: app
    image: payment-service:2.3.1
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
      limits:
        memory: "1Gi"
        cpu: "1000m"
    env:
    - name: JAVA_OPTS
      value: "-Xms512m -Xmx768m"
```

**注意**：
- 内存限制建议设为 requests 的 1.5~2 倍，避免 OOMKill
- CPU 限制可适当放宽，但不应超过节点总 CPU 的 80%

### 4.3 QoS 等级配置

根据资源配置自动确定 QoS 等级：

| QoS 等级 | 配置方式 | 行为特征 |
|----------|----------|----------|
| Guaranteed | requests == limits（所有容器） | 优先级最高，几乎不会被驱逐 |
| Burstable | requests < limits 且至少一个容器设requests | 中等优先级，可能被驱逐 |
| BestEffort | 未设置任何 requests/limits | 最低优先级，资源紧张时优先驱逐 |

**Guaranteed 示例**：
```yaml
resources:
  requests:
    memory: "2Gi"
    cpu: "1"
  limits:
    memory: "2Gi"
    cpu: "1"
```

### 4.4 命名空间资源配额 (ResourceQuota)

防止单个团队或应用过度消耗集群资源。

**示例 ResourceQuota**：
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-alpha-quota
  namespace: team-alpha
spec:
  hard:
    requests.cpu: "10"
    requests.memory: "20Gi"
    limits.cpu: "20"
    limits.memory: "40Gi"
    requests.nvidia.com/gpu: 4
    persistentvolumeclaims: "10"
    count/deployments.apps: "20"
```

**监控命令**：
```bash
kubectl describe resourcequota team-alpha-quota -n team-alpha
```

### 4.5 LimitRange 配置

设置命名空间内 Pod 的默认资源限制。

**示例 LimitRange**：
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
  - max:
      cpu: "4"
      memory: "8Gi"
    min:
      cpu: "100m"
      memory: "64Mi"
    default:
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:
      cpu: "200m"
      memory: "256Mi"
    type: Container
```

---

## 5. GPU 调度说明

GPU 资源为受限扩展资源，需特殊处理。

**前提条件**：
- 节点安装 NVIDIA 驱动 (>= 418.81.07)
- 部署 nvidia-device-plugin DaemonSet
- 节点标记 `nvidia.com/gpu` 标签

**Pod 配置示例**：
```yaml
spec:
  containers:
  - name: gpu-inference
    image: inference:1.0
    resources:
      requests:
        nvidia.com/gpu: 1
      limits:
        nvidia.com/gpu: 1
```

**注意**：GPU 资源必须设置 requests == limits，否则调度失败。

---

## 6. 常见问题与排查

### 6.1 Pod 处于 Pending 状态

**排查命令**：
```bash
kubectl describe pod <pod-name> -n <namespace>
```

**常见原因**：
1. 节点资源不足（CPU/内存）
2. 节点选择器不匹配
3. 节点污点（Taint）未容忍
4. GPU 资源不可用

**解决方案**：
- 使用 `kubectl top nodes` 查看节点资源使用率
- 检查节点标签：`kubectl get nodes --show-labels`

### 6