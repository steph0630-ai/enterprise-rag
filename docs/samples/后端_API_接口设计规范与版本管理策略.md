# 后端 API 接口设计规范与版本管理策略

| 文档编号 | TEC-API-2024-001 |
|---------|-----------------|
| 版本号 | v2.3 |
| 生效日期 | 2024-10-15 |
| 负责人 | 张三（后端架构组） |
| 审批人 | 李四（技术VP） |

---

## 变更记录

| 版本 | 日期 | 变更描述 | 作者 |
|-----|------|---------|------|
| v1.0 | 2023-06-01 | 初始版本，定义RESTful接口基础规范 | 张三 |
| v2.0 | 2024-01-15 | 引入版本管理策略，增加gRPC支持 | 王五 |
| v2.1 | 2024-05-20 | 细化错误码规范，增加分页参数标准 | 张三 |
| v2.2 | 2024-08-10 | 新增Webhook回调接口规范 | 赵六 |
| v2.3 | 2024-10-15 | 更新认证鉴权流程，增加限流策略 | 张三 |

---

## 1. 概述

本文档定义了公司内部所有后端微服务对外暴露的 API 接口设计规范，涵盖 RESTful 与 gRPC 两种协议。所有新开发的服务必须遵循本规范，存量服务需在 v3 版本切换时逐步对齐。

### 1.1 适用范围

- 所有面向移动端、Web 前端、第三方合作伙伴的 HTTP API
- 内部服务间通信的 gRPC 接口
- 异步回调（Webhook）接口

### 1.2 核心原则

- **向后兼容性**：同一主版本号内不得引入 Breaking Change
- **幂等性**：GET、PUT、DELETE 必须幂等，POST 可选
- **无状态**：所有请求应携带完整上下文，不依赖服务端 Session

---

## 2. RESTful API 设计规范

### 2.1 URL 命名规则

- 全部使用小写字母，单词间以 `-` 分隔
- 路径以资源名为核心，避免动词
- 版本号放在 URL 前缀中

**格式**：`/api/v{major}/{resource}[/{resource_id}][?query_params]`

**示例**：
```
# 正确
GET /api/v2/users
GET /api/v2/users/12345
POST /api/v2/users

# 错误（使用动词）
GET /api/v2/getUserInfo
POST /api/v2/createUser
```

### 2.2 HTTP 方法对应语义

| 方法 | 操作 | 幂等 | 请求体 | 响应体 |
|------|------|------|--------|--------|
| GET | 查询资源列表或单个资源 | 是 | 无 | 资源对象或数组 |
| POST | 创建资源或触发动作 | 否 | 资源数据 | 新创建的资源 |
| PUT | 全量替换资源 | 是 | 完整资源数据 | 更新后的资源 |
| PATCH | 部分更新资源 | 是 | 增量字段 | 更新后的资源 |
| DELETE | 删除资源 | 是 | 无 | 空或删除确认 |

### 2.3 请求与响应格式

#### 2.3.1 请求头必填字段

```http
Content-Type: application/json
Accept: application/json
Authorization: Bearer <access_token>
X-Request-Id: <uuid>    # 用于链路追踪
```

#### 2.3.2 标准响应结构

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "usr_001",
    "name": "张三",
    "email": "zhangsan@example.com",
    "created_at": "2024-10-15T08:00:00Z"
  },
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**分页响应**：
```json
{
  "code": 0,
  "data": {
    "items": [...],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 156,
      "total_pages": 8
    }
  },
  "request_id": "..."
}
```

### 2.4 错误码规范

| 范围 | 含义 | 示例 |
|------|------|------|
| 0 | 成功 | - |
| 1000-1999 | 客户端参数错误 | 1001: 缺少必填字段 |
| 2000-2999 | 认证鉴权错误 | 2001: Token过期 |
| 3000-3999 | 资源错误 | 3001: 资源不存在 |
| 4000-4999 | 业务逻辑错误 | 4001: 余额不足 |
| 5000-5999 | 服务端错误 | 5001: 数据库超时 |

**错误响应示例**：
```json
{
  "code": 1001,
  "message": "参数校验失败",
  "details": {
    "field": "email",
    "reason": "格式不正确，必须包含@符号"
  },
  "request_id": "..."
}
```

---

## 3. 版本管理策略

### 3.1 版本号格式

采用 **主版本号.次版本号.修订号** 格式，仅主版本号体现在 URL 中。

- **主版本号（Major）**：引入 Breaking Change 时递增，如 `/api/v1/` → `/api/v2/`
- **次版本号（Minor）**：新增向后兼容的功能时递增
- **修订号（Patch）**：向后兼容的 Bug 修复时递增

### 3.2 版本生命周期

| 阶段 | 状态 | 说明 | 维护要求 |
|------|------|------|----------|
| Alpha | 内部测试 | 仅开发环境可用 | 随时可变更 |
| Beta | 公开预览 | 预发布环境，开放给部分合作伙伴 | 修复严重缺陷 |
| Stable | 正式发布 | 生产环境 | 完全向后兼容 |
| Deprecated | 废弃 | 不再推荐使用，保留180天 | 仅修复安全漏洞 |
| Sunset | 下线 | 彻底移除 | 提前60天通知 |

### 3.3 版本兼容性规则

- 同一主版本内的所有接口必须保持**二进制兼容**（字段顺序、类型不变）
- 允许新增可选字段，不允许删除或修改已有字段名
- 允许新增接口，不允许修改已有接口的语义
- 废弃接口需在响应头中增加 `X-API-Deprecated: true` 标识

**版本声明示例**：
```yaml
# OpenAPI 3.0 规范
openapi: "3.0.0"
info:
  title: User Service API
  version: "2.5.1"
  x-api-lifecycle: "Stable"
  x-sunset-date: "2025-06-30"
```

### 3.4 版本迁移策略

当需要升级主版本时，需遵循以下流程：

1. **并行运行**：新旧版本同时运行至少 90 天
2. **灰度切换**：通过 Nginx 或 API Gateway 按流量比例灰度
3. **客户端升级**：要求所有调用方在 60 天内完成升级
4. **强制迁移**：旧版本下线前 30 天，返回 301 重定向并记录日志

**Nginx 灰度配置示例**：
```nginx
split_clients "${remote_addr}${http_user_agent}" $api_version {
    10%    "v2";
    *      "v1";
}

location /api/ {
    proxy_pass http://backend_$api_version;
}
```

---

## 4. gRPC 接口规范

### 4.1 Proto 文件命名

- 文件命名：`{service_name}.proto`，如 `user_service.proto`
- Package 命名：`com.company.{domain}.{service}.v{major}`

### 4.2 消息定义规范

```protobuf
syntax = "proto3";

package com.company.user.v2;

message GetUserRequest {
  string user_id = 1;
}

message GetUserResponse {
  string id = 1;
  string name = 2;
  string email = 3;
  int64 created_at = 4;  // Unix timestamp
}

service UserService {
  rpc GetUser(GetUserRequest) returns (GetUserResponse);
}
```

### 4.3 版本管理

- gRPC 版本号通过 package 中的 v{major} 标识
- 同一主版本内，字段编号（field number）不可复用
- 废弃字段使用 `reserved` 关键字标记

---

## 5. 认证与鉴权

### 5.1 认证流程

所有 API 请求必须携带有效的 JWT Access Token，通过 `Authorization: Bearer <token>` 传递。

**Token 格式**：
```json
{
  "sub": "usr_001",
  "tenant_id": "tnt_abc",
  "roles": ["admin",