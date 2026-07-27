# 多租户 SaaS 架构设计与数据隔离方案

| 文档编号 | 版本 | 编写人 | 审核人 | 批准人 | 生效日期 |
|----------|------|--------|--------|--------|----------|
| TEC-SaaS-001 | V2.1 | 张明 | 李磊 | 王浩 | 2025-03-10 |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| V1.0 | 2024-06-01 | 初始版本 | 张明 |
| V1.2 | 2024-09-15 | 增加混合隔离模式 | 赵岩 |
| V2.0 | 2025-01-20 | 重构数据层，引入ShardingSphere | 张明 |
| V2.1 | 2025-03-10 | 增加租户密钥管理规范 | 陈晓 |

## 1. 概述

本文档描述企业级多租户 SaaS 平台的核心架构设计，重点阐述数据隔离策略及实现细节。本设计适用于租户数量在 1000 以上、单租户数据量可达 50GB 的中大型 SaaS 场景。核心目标为：**保证租户间数据安全隔离、降低运维成本、支持租户级弹性扩展**。

## 2. 架构总览

系统采用三层架构：**接入层 - 服务层 - 数据层**。租户上下文（Tenant Context）在每一层传递。

```text
+---------------------+       +---------------------+
|     接入层 (API GW)  |       | 租户识别、路由      |
|  - Nginx + Lua      |       | 解析 X-Tenant-ID    |
+--------+------------+       +---------------------+
         |
+--------v------------+       +---------------------+
|     服务层 (K8s)     |       | 业务逻辑 + 数据路由  |
|  - Spring Cloud     |       | TenantContextHolder |
|  - Istio Sidecar    |       | 传递租户标识        |
+--------+------------+       +---------------------+
         |
+--------v------------+       +---------------------+
|     数据层 (MySQL)   |       | 数据隔离实现        |
|  - ShardingSphere   |       | 分库/分表/加密     |
+---------------------+       +---------------------+
```

### 2.1 租户识别与上下文传递

- 所有外部请求必须携带 `X-Tenant-ID` Header（由 API Gateway 校验）。
- 内部服务间通过 gRPC Metadata 传递租户 ID。
- 每个服务启动时初始化 `TenantContextHolder`，使用 ThreadLocal 存储当前请求的租户 ID。

```java
public class TenantContextHolder {
    private static final ThreadLocal<String> CONTEXT = new ThreadLocal<>();
    
    public static void setTenantId(String tenantId) {
        CONTEXT.set(tenantId);
    }
    
    public static String getTenantId() {
        return CONTEXT.get();
    }
    
    public static void clear() {
        CONTEXT.remove();
    }
}
```

## 3. 数据隔离策略

根据业务敏感度与数据量级，采用 **混合隔离模式**：

| 隔离级别 | 实现方式 | 适用场景 | 租户数上限 | 运维成本 |
|----------|----------|----------|------------|----------|
| S1 - 完全独立 | 每租户独立 DB | 金融、医疗 | < 200 | 高 |
| S2 - 共享库 | 同一 DB，分 Schema | 中型企业 | < 500 | 中 |
| S3 - 共享表 | 同一 Schema，tenant_id 列 | 通用业务 | > 1000 | 低 |

### 3.1 默认策略：S3 共享表 + 分表

对于绝大多数业务表（用户、订单、产品），采用 **按租户 ID 分表** 策略：

- 分片键：`tenant_id`
- 分片算法：`tenant_id % 64`（取模后分配至 64 张物理表，如 `orders_0`, `orders_1`, ... `orders_63`）
- 使用 Apache ShardingSphere 5.x 实现。

**ShardingSphere 配置示例（YAML）**：

```yaml
rules:
  - !SHARDING
    tables:
      orders:
        actualDataNodes: ds_0.orders_${0..63}
        tableStrategy:
          standard:
            shardingColumn: tenant_id
            shardingAlgorithmName: orders_inline
        keyGenerateStrategy:
          column: id
          keyGeneratorName: snowflake
    shardingAlgorithms:
      orders_inline:
        type: INLINE
        props:
          algorithm-expression: orders_${tenant_id % 64}
    keyGenerators:
      snowflake:
        type: SNOWFLAKE
        props:
          worker-id: 1
```

### 3.2 高安全场景：S1 独立库

当租户要求数据完全隔离（如合规审计场景），自动为该租户创建独立 MySQL 实例。创建流程：

1. 运维平台调用 `create_tenant_db.sh` 脚本。
2. 脚本执行 `CREATE DATABASE` 并初始化表结构。
3. 记录租户 ID 与数据源映射至 `tenant_datasource` 配置表。
4. 应用启动时加载映射，根据租户 ID 动态切换 DataSource。

```sql
-- tenant_datasource 表结构
CREATE TABLE tenant_datasource (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL UNIQUE,
    db_host VARCHAR(255) NOT NULL,
    db_port INT NOT NULL DEFAULT 3306,
    db_name VARCHAR(100) NOT NULL,
    username VARCHAR(100) NOT NULL,
    password_encrypted VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 示例数据
INSERT INTO tenant_datasource (tenant_id, db_host, db_port, db_name, username, password_encrypted)
VALUES ('TENANT-001', '192.168.1.101', 3306, 'db_tenant_001', 'user_001', 'AES_ENCRYPTED_STRING');
```

### 3.3 敏感字段加密

对于 PII 数据（如手机号、邮箱），即使共享表也需加密存储。使用 AES-256-GCM 算法，每个租户独立密钥。

```java
// 加密工具类示例
public class TenantCipher {
    private static final Map<String, SecretKey> KEY_CACHE = new ConcurrentHashMap<>();
    
    public static String encrypt(String tenantId, String plainText) {
        SecretKey key = getOrCreateKey(tenantId);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        byte[] iv = cipher.getIV();
        byte[] encrypted = cipher.doFinal(plainText.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(iv) + ":" + Base64.getEncoder().encodeToString(encrypted);
    }
    
    private static SecretKey getOrCreateKey(String tenantId) {
        return KEY_CACHE.computeIfAbsent(tenantId, id -> {
            // 从密钥管理服务（KMS）获取或生成密钥
            return KMSClient.fetchKey("tenant_" + id);
        });
    }
}
```

## 4. 租户管理流程

### 4.1 创建租户

通过内部管理 API 创建新租户，执行以下步骤：

1. **注册租户信息**：调用 `POST /api/v1/tenants`，传入 `name, contact_email, plan_type`。
2. **分配租户 ID**：生成 16 位 UUID（如 `TENANT-4a3c2b1e`）。
3. **选择隔离模式**：根据 `plan_type` 决定隔离级别：
   - `enterprise` → S1 独立库
   - `standard` → S3 共享表
4. **初始化资源**：创建数据源或分表，生成加密密钥。
5. **返回配置**：返回 `tenant_id` 及初始 `api_key`。

### 4.2 租户迁移

当租户从 S3 升级至 S1 时，执行在线迁移：

```bash
# 迁移脚本示例
./migrate_tenant.sh --tenant-id TENANT-001 --target-isolation S1 --source-db ds_0 --target-db ds_tenant_001
```

迁移过程采用双写模式，确保数据一致性。

## 5. 监控与告警

| 指标 | 阈值 | 告警级别 |
|------|------|----------|
| 单租户订单表行数 | > 5000万 | Warning |
| 单租户数据库连接数 | > 80% 上限 | Critical |
| 跨租户数据访问尝试 | 每分钟 > 3次 | Critical |
| 加密密钥轮换超时 | 超过 24小时 | Warning |

## 6. 注意事项

1. **禁止使用 `SELECT *`**：所有查询必须显式指定列