# Nginx 反向代理与负载均衡配置指南

| 文档版本 | 修改日期     | 修改人   | 修改内容                     |
| -------- | ------------ | -------- | ---------------------------- |
| V1.0     | 2024-01-15   | 张伟     | 初始版本创建，基础配置说明   |
| V1.1     | 2024-03-22   | 李娜     | 增加健康检查与日志优化配置   |
| V1.2     | 2024-06-10   | 王强     | 更新 SSL 卸载与 upstream 权重策略 |

**负责人**：张伟（运维组）  
**适用范围**：生产环境所有 Nginx 节点（版本 ≥ 1.20）  
**相关服务**：API Gateway、Web 应用服务器组、静态资源服务器

---

## 1. 概述

本指南用于规范 Nginx 在生产环境中的反向代理与负载均衡配置。通过 Nginx 的 `upstream` 模块实现流量分发，支持多种负载均衡算法，并提供 SSL 终止、健康检查、缓存加速等能力。所有配置需遵循公司《服务器安全基线》与《高可用架构规范》。

---

## 2. 基础架构

### 2.1 网络拓扑

```
客户端 (Internet)
       |
       v
    +-------+
    | Nginx |   (公网 IP: 203.0.113.10, 内网 IP: 10.10.1.10)
    +---+---+
        |
        | 内网 10.10.1.x
        |
   +----+----+----+
   |    |    |    |
   v    v    v    v
  Web1  Web2  Web3  Static
 (10.10.2.11) (10.10.2.12) (10.10.2.13) (10.10.2.20)
```

### 2.2 组件说明

- **Nginx 节点**：2 台（主备模式，通过 keepalived 实现 VIP 漂移）
- **后端 Web 服务器**：3 台 Tomcat 节点，端口 8080
- **静态资源服务器**：1 台 Nginx 节点，端口 80

---

## 3. 负载均衡配置

### 3.1 upstream 配置

在 `/etc/nginx/conf.d/upstream.conf` 中定义后端服务器组：

```nginx
upstream backend_web {
    # 负载均衡算法：least_conn（最少连接数）
    least_conn;

    # 后端服务器列表（权重为 3:2:1）
    server 10.10.2.11:8080 weight=3 max_fails=3 fail_timeout=30s;
    server 10.10.2.12:8080 weight=2 max_fails=3 fail_timeout=30s;
    server 10.10.2.13:8080 weight=1 max_fails=3 fail_timeout=30s;

    # 健康检查（仅限商业版或使用 ngx_http_upstream_check_module）
    check interval=3000 rise=2 fall=5 timeout=1000 type=http;
    check_http_send "GET /health HTTP/1.0\r\n\r\n";
    check_http_expect_alive http_2xx http_3xx;
}

upstream static_assets {
    server 10.10.2.20:80 weight=5;
    # 备用服务器（当所有主服务器不可用时启用）
    server 10.10.2.21:80 backup;
}
```

### 3.2 反向代理配置

在 `/etc/nginx/conf.d/proxy.conf` 中配置代理行为：

```nginx
server {
    listen 80;
    server_name api.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    # SSL 证书配置
    ssl_certificate /etc/nginx/ssl/api.example.com.pem;
    ssl_certificate_key /etc/nginx/ssl/api.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 代理配置
    location / {
        proxy_pass http://backend_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时设置
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;

        # 缓冲优化
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
        proxy_busy_buffers_size 8k;
    }

    # 静态资源分离
    location /static/ {
        proxy_pass http://static_assets;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

---

## 4. 负载均衡算法说明

| 算法             | 配置指令           | 适用场景                         | 注意事项                     |
| ---------------- | ------------------ | -------------------------------- | ---------------------------- |
| 轮询（默认）     | 无 / `round-robin` | 后端性能均匀                     | 默认行为，无需显式声明       |
| 最少连接         | `least_conn`       | 请求处理时间差异大               | 需结合健康检查               |
| IP 哈希          | `ip_hash`          | 会话保持（Session Sticky）       | 可能导致负载不均             |
| 哈希（URL 等）   | `hash $request_uri`| 缓存命中优化                     | 需指定 key                   |
| 随机             | `random`           | 大规模集群的简单分发             | 不可预测性高                 |

> **生产建议**：对于无状态 API 服务，优先使用 `least_conn`；对于需要会话保持的场景，使用 `ip_hash` 并配合 Redis Session 共享。

---

## 5. 健康检查与故障转移

### 5.1 被动健康检查

Nginx 默认通过 `max_fails` 和 `fail_timeout` 实现被动检测：

```nginx
server 10.10.2.11:8080 max_fails=3 fail_timeout=30s;
# 含义：30 秒内失败 3 次，则标记为不可用，30 秒后重新尝试
```

### 5.2 主动健康检查（商业版 / 第三方模块）

若使用 Nginx Plus 或编译了 `nginx_upstream_check_module`，可配置主动检查：

```nginx
upstream backend_web {
    # 每 3 秒检查一次，连续 2 次成功恢复，连续 5 次失败下线
    check interval=3000 rise=2 fall=5 timeout=1000 type=http;
    check_http_send "GET /health HTTP/1.0\r\n\r\n";
    check_http_expect_alive http_2xx http_3xx;
}
```

### 5.3 故障转移验证

```bash
# 模拟后端宕机
$ systemctl stop tomcat@web1.service

# 查看 Nginx 日志确认故障转移
$ tail -f /var/log/nginx/error.log | grep "upstream"
2024/06/10 14:30:22 [error] 12345#0: *789 upstream timed out (110: Connection timed out) while connecting to upstream, client: 10.10.1.100, server: api.example.com, request: "GET /api/v1/users HTTP/1.1", upstream: "http://10.10.2.11:8080/api/v1/users"

# 验证请求被分发到其他节点
$ curl -I https://api.example.com/api/v1/users
HTTP/2 200
```

---

## 6. 性能优化配置

### 6.1 连接与缓冲区优化

在 `nginx.conf` 的 `http` 块中调整：

```nginx
http {
    # 工作进程与连接
    worker_processes auto;
    worker_connections 10240;
    multi_accept on;
    use epoll;

    # 文件描述符限制
    worker_rlimit_nofile 65535;

    # 发送缓冲
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # 客户端连接
    keepalive_timeout 65;
    keepalive_requests 100;
    client_max_body_size 20m;
    client_body_buffer_size 128k;
}
```

### 6.2 SSL 性能调优

```nginx
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
ssl_session_tickets off;
# 启用 OCSP Stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 1.1.1.1 valid=300s;
resolver_timeout 5s