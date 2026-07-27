# 故障复盘报告：证书过期导致全站 HTTPS 不可用事故

| 文档编号 | FPR-2024-003 |
|---------|------------|
| 版本号 | 1.2 |
| 创建日期 | 2024-08-15 |
| 最后更新 | 2024-08-17 |
| 负责人 | 张伟（SRE团队） |
| 审核人 | 李明（安全架构师）、王芳（运维总监） |

---

## 1. 事件概述

**事故等级**：P0（核心业务完全不可用）  
**影响范围**：所有通过 HTTPS 访问主站（www.example.com）及 API 服务（api.example.com）的用户，影响时长约 47 分钟。  
**直接后果**：  
- 全站 HTTPS 请求返回 502/SSL_ERROR 错误，用户无法登录、下单、查询订单。  
- 期间 HTTP 未受影响，但默认强制跳转 HTTPS，因此 HTTP 访问同样失败。  
- 预估损失订单金额约 80 万元，品牌声誉影响待评估。

## 2. 时间线

| 时间 (UTC+8) | 事件描述 |
|-------------|---------|
| 2024-08-15 09:12 | 监控告警：全站 HTTPS 响应时间超阈值，错误率飙升到 100% |
| 09:14 | SRE 值班人员确认故障，定位到 SSL 握手失败 |
| 09:18 | 检查证书发现 `*.example.com` 通配符证书已过期（过期时间 2024-08-15 08:59:59） |
| 09:22 | 紧急启用备用证书（有效期至 2025-02-01） |
| 09:28 | 证书替换到 Nginx 后，`nginx -s reload` 操作 |
| 09:35 | 部分节点仍未生效，排查发现 CDN 节点缓存旧证书 |
| 09:42 | 强制刷新 CDN 边缘节点缓存 |
| 09:49 | 全站 HTTPS 恢复，错误率降至 0.1% |
| 10:00 | 确认 100% 恢复，关闭告警 |

## 3. 根因分析

### 3.1 直接原因
证书 `*.example.com`（序列号 `04:AB:CD:EF:12:34`）于 2024-08-15 08:59:59 过期，但未在到期前完成续期和替换。

### 3.2 根本原因

1. **证书自动续期机制失效**  
   - 此前使用 `certbot` 进行 Let's Encrypt 自动续期，但 2024-07-01 进行了 Nginx 配置重构，将证书路径从 `/etc/letsencrypt/live/` 改为 `/etc/ssl/certs/`。  
   - 重构后未更新 `certbot` 的 `--webroot` 路径参数，导致自动续期脚本始终无法验证域名所有权（404 错误），自 2024-07-15 起连续 30 次续期失败，但告警被忽略。

2. **证书监控缺失**  
   - 证书过期检查脚本 `check_cert_expiry.sh` 因服务器迁移后 cron 任务未启用，自 2024-06-01 起未执行。  
   - Prometheus 的 `ssl_expiry_seconds` 指标在 Grafana 中未配置告警规则。

3. **人为疏忽**  
   - 2024-08-14 轮值 SRE 工程师在日报中标记了 "证书即将到期，需关注"，但未升级为工单或任务。  
   - 证书过期当天为周四，原计划周五（08-16）执行续期，但未考虑到证书在周四上午 9 点过期。

### 3.3 技术细节

**Nginx 配置片段（故障时）**：
```nginx
server {
    listen 443 ssl;
    server_name www.example.com api.example.com;
    
    ssl_certificate     /etc/ssl/certs/example_com.pem;
    ssl_certificate_key /etc/ssl/certs/example_com.key;
    # 证书实际已经过期
}
```

**证书信息**：
```
$ openssl x509 -in /etc/ssl/certs/example_com.pem -noout -dates
notBefore=Aug 15 09:00:00 2023 GMT
notAfter=Aug 15 08:59:59 2024 GMT   ← 已过期
```

**错误日志**（从 Nginx error.log 提取）：
```
2024/08/15 09:12:34 [error] 12345#0: *6789 SSL_do_handshake() failed (SSL: error:14094415:SSL routines:ssl3_read_bytes:sslv3 alert certificate expired) while SSL handshaking, client: 192.168.1.100, server: 0.0.0.0:443
```

## 4. 修复措施

### 4.1 应急修复（已完成）

1. **立即替换证书**  
   - 从备份系统提取 2024-08-01 生成的备用证书（有效期至 2025-02-01）。  
   - 替换 Nginx 配置中的证书文件路径。

2. **强制重新加载 Nginx**  
   ```bash
   nginx -t && systemctl reload nginx
   ```
   注意：使用 `reload` 而非 `restart`，避免中断已有长连接。

3. **清除 CDN 缓存**  
   - 在 CDN 管理后台（CloudFront）执行全站缓存失效操作：
   ```bash
   aws cloudfront create-invalidation --distribution-id E123456789 --paths "/*"
   ```

### 4.2 长期改进（待实施）

| 改进项 | 负责人 | 截止日期 | 状态 |
|-------|--------|---------|------|
| 修复 certbot 自动续期路径 | 张伟 | 2024-08-18 | 进行中 |
| 部署证书过期监控告警（Prometheus + Alertmanager） | 赵强 | 2024-08-20 | 未开始 |
| 建立证书生命周期管理流程（30 天、14 天、7 天、1 天预警） | 李明 | 2024-08-25 | 未开始 |
| 自动化证书替换脚本，集成到 CI/CD | 王芳 | 2024-09-01 | 未开始 |

## 5. 经验教训

1. **自动化不等于免维护**：自动续期脚本的配置变更需同步通知相关团队，且必须设置定期验证。  
2. **监控必须分层**：证书过期监控应既包括主动检查（脚本），也包括被动告警（Prometheus 指标）。  
3. **到期日管理**：证书过期时间通常为到期日 00:00:00 UTC（对应北京时间 08:00），应提前至少 7 天处理。  
4. **变更管理**：Nginx 配置重构导致证书路径变更，应触发证书相关流程的 review。

## 6. 附录

### 6.1 证书检查脚本（修复后版本）

```bash
#!/bin/bash
# check_cert_expiry.sh - 检查证书剩余有效期并告警
CERT_PATH="/etc/ssl/certs/example_com.pem"
EXPIRY=$(openssl x509 -in "$CERT_PATH" -noout -enddate | cut -d= -f2)
EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 7 ]; then
    echo "WARNING: Certificate expires in $DAYS_LEFT days!"
    # 发送告警到 Slack
    curl -X POST -H "Content-type: application/json" \
        --data "{\"text\":\"Certificate $CERT_PATH expires in $DAYS_LEFT days\"}" \
        https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXX
fi
```

### 6.2 Prometheus 告警规则

```yaml
groups:
  - name: ssl_expiry
    rules:
      - alert: SSLCertExpiringSoon
        expr: ssl_expiry_seconds{domain="www.example.com"} < 604800  # 7天
        for: 1h
        annotations:
          summary: "SSL certificate for {{ $labels.domain }} will expire in {{ $value | humanizeDuration }}"
```

---

**变更记录**：

| 版本 | 日期 | 修改人 | 说明 |
|------|------|--------|------|
| 1.0 | 2024-08-15 | 张伟 | 初始版本 |
| 1.1 | 2024-08-16 | 李明 | 补充根因分析，修改时间线 |
| 1.2 | 2024-08-17 | 王芳 | 添加长期改进计划，更新附录 |

**分发范围**：SRE 