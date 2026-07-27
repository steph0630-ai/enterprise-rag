# Docker 镜像构建规范与镜像仓库管理

| 文档版本 | 修订日期       | 修订人     | 修订内容                     |
| -------- | -------------- | ---------- | ---------------------------- |
| V1.0     | 2024-03-15     | 张磊       | 初稿创建                     |
| V1.1     | 2024-06-20     | 李明       | 新增多阶段构建规范及仓库清理策略 |
| V1.2     | 2024-09-10     | 王芳       | 更新镜像标签命名规则及安全扫描流程 |

**负责人：** 运维部 - 容器平台组  
**审批人：** 基础设施总监 - 陈涛  
**生效日期：** 2024-09-15  

---

## 1. 概述

本文档规定了公司内部 Docker 镜像的构建标准、镜像标签命名规范、镜像仓库使用流程以及日常管理策略。所有涉及 Docker 镜像构建和推送的开发、测试及运维人员必须遵循本规范，以确保镜像一致性、可追溯性及安全性。

## 2. 镜像构建规范

### 2.1 基础镜像选择

- **操作系统基础镜像：** 优先使用 `alpine:3.18` 或 `debian:11-slim`，避免使用 `ubuntu:latest` 等无版本标签。
- **语言运行时镜像：** 使用官方镜像如 `python:3.11-slim`、`node:20-alpine`、`openjdk:17-jre-slim`。
- **禁止使用 root 用户运行容器进程**，必须在 Dockerfile 中创建非 root 用户并切换。

### 2.2 Dockerfile 编写规范

- 每个 `RUN` 命令应合并，减少镜像层数。
- 使用 `.dockerignore` 排除非必要文件（如 `.git`、`node_modules`、`__pycache__`）。
- 必须使用 **多阶段构建（multi-stage builds）** 分离编译环境和运行环境。

**示例 Dockerfile（Java 项目）：**

```dockerfile
# Stage 1: Build
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests

# Stage 2: Runtime
FROM eclipse-temurin:17-jre-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
USER appuser
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**示例 .dockerignore 文件：**

```
.git
.gitignore
*.md
target/
logs/
.env
node_modules/
```

### 2.3 镜像标签命名规则

标签格式：`<项目代号>/<服务名称>:<语义版本>-<构建环境>-<构建编号>`

- **项目代号：** 小写英文缩写，如 `pay`、`auth`、`order`。
- **服务名称：** 具体微服务名称，如 `payment-service`、`user-api`。
- **语义版本：** 遵循 SemVer 规范，如 `1.2.3`。
- **构建环境：** `prod`（生产）、`staging`（预发布）、`dev`（开发）。
- **构建编号：** CI/CD 流水线自动生成的数字编号。

**示例：**

```
pay/payment-service:1.3.0-prod-245
auth/user-api:2.0.1-staging-89
```

> **注意：** 禁止使用 `latest` 标签。生产环境必须使用精确的版本标签。

## 3. 镜像构建与推送流程

### 3.1 构建命令

开发人员或 CI 流水线执行以下命令构建镜像：

```bash
# 构建镜像
docker build -t registry.company.com/pay/payment-service:1.3.0-prod-245 -f Dockerfile .

# 登录私有仓库（仅首次或凭证过期时）
docker login registry.company.com -u <username> -p <password>

# 推送镜像
docker push registry.company.com/pay/payment-service:1.3.0-prod-245
```

### 3.2 镜像签名与安全扫描

所有推送到生产环境的镜像必须经过以下步骤：

1. **安全扫描：** 使用 Trivy 扫描 CVE 漏洞。

```bash
trivy image --severity HIGH,CRITICAL registry.company.com/pay/payment-service:1.3.0-prod-245
```

2. **镜像签名：** 使用 Cosign 对镜像进行签名。

```bash
cosign sign --key cosign.key registry.company.com/pay/payment-service:1.3.0-prod-245
```

3. **仅允许已签名且无高危漏洞的镜像部署到生产集群**（通过 OPA/Gatekeeper 策略强制执行）。

### 3.3 镜像仓库配置

公司使用 **Harbor** 作为私有镜像仓库，地址为 `registry.company.com`。仓库结构如下：

| 项目名称          | 用途描述                       | 访问权限       |
| ----------------- | ------------------------------ | -------------- |
| pay               | 支付业务线所有镜像             | 开发+运维      |
| auth              | 认证授权相关镜像               | 开发+运维      |
| order             | 订单服务相关镜像               | 开发+运维      |
| base-images       | 基础镜像（如定制化的 JDK 镜像）| 仅运维         |
| public            | 公开的中间件镜像（如 Nginx）   | 所有人只读     |

## 4. 镜像仓库管理策略

### 4.1 保留策略

- **生产镜像：** 保留最近 30 个版本（按构建编号降序），自动清理更早的版本。
- **预发布镜像：** 保留最近 10 个版本。
- **开发镜像：** 保留最近 5 个版本，且超过 7 天未使用的镜像自动删除。
- **基础镜像：** 保留所有历史版本，需手动审批删除。

### 4.2 镜像垃圾回收（GC）

运维人员每月执行一次垃圾回收，释放未被任何标签引用的镜像层占用的存储空间。

```bash
# Harbor 手动 GC（需在 Harbor 管理界面执行）
# 或通过 API 触发：
curl -X POST "https://registry.company.com/api/v2.0/system/gc/schedule" \
  -H "Content-Type: application/json" \
  -d '{"schedule": {"type": "Manual"}}'
```

### 4.3 镜像复制与同步

- 若存在多个数据中心，Harbor 支持跨地域复制（Replication）功能。
- 生产仓库 `prod-harbor` 中的镜像自动复制到灾备仓库 `dr-harbor`。
- 复制规则：仅复制标签匹配 `*-prod-*` 的镜像。

## 5. 常见问题与故障处理

### 5.1 镜像推送失败

**现象：** `denied: requested access to the resource is denied`  
**原因：** 用户没有该项目的推送权限。  
**解决：** 联系运维组在 Harbor 中为用户添加对应项目的 `developer` 角色。

### 5.2 镜像空间不足

**现象：** `no space left on device`  
**原因：** 本地 Docker 存储目录 `/var/lib/docker` 已满。  
**解决：**

```bash
# 清理未被使用的镜像、容器和数据卷
docker system prune -a --volumes

# 或指定清理超过 24 小时的 dangling 镜像
docker image prune -a --filter "until=24h"
```

## 6. 附则

- 所有违反本规范的镜像构建将不被允许推送到生产仓库。
- 开发环境可使用临时标签（如 `dev-latest`），但不得推送至生产项目。
- 本规范由容器平台组负责解释和更新，每季度评审一次。

---

**相关文档：**
- 《Kubernetes 部署规范 V2.0》
- 《Harbor 管理员操作手册 V1.5》
- 《容器安全基线检查清单 V3.1`