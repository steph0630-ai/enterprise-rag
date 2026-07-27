# MySQL 数据库部署与配置规范

| 文档版本 | 修订日期   | 修订人   | 修订内容                     |
|----------|------------|----------|------------------------------|
| v1.0     | 2024-05-20 | 李响     | 初稿创建                     |
| v1.1     | 2024-08-15 | 王澜     | 增加参数模板及备份策略章节   |

**负责人**：张明（DBA Team Lead）  
**适用范围**：生产环境、预发布环境、测试环境（准生产环境除外需另行审批）

---

## 1. 环境要求

### 1.1 操作系统与内核参数

所有部署节点必须满足以下条件：

- 操作系统：CentOS 7.9+ / Rocky Linux 8.6+ / Ubuntu 20.04 LTS
- 内核参数优化（`/etc/sysctl.conf`）：

```ini
# 内核参数优化
fs.file-max = 6815744
net.core.somaxconn = 32768
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
```

应用后执行 `sysctl -p` 生效。

### 1.2 磁盘与文件系统

- 使用 SSD 磁盘，建议 NVMe 盘
- 文件系统：XFS（推荐）或 ext4，挂载参数增加 `noatime,nodiratime`
- 数据盘单独挂载至 `/data/mysql`，日志盘单独挂载至 `/data/mysql_log`（如果使用独立日志盘）

---

## 2. 安装部署

### 2.1 安装方式

统一使用 MySQL 官方发布的二进制 tar 包安装，禁止使用系统包管理器（yum/apt）安装社区版。

当前标准版本：**MySQL 8.0.35**

### 2.2 安装步骤

```bash
# 创建 mysql 用户（uid/gid 3000，保持各节点一致）
groupadd -g 3000 mysql
useradd -u 3000 -g mysql -s /sbin/nologin -d /data/mysql mysql

# 下载并解压
cd /usr/local
wget https://cdn.mysql.com/archives/mysql-8.0/mysql-8.0.35-linux-glibc2.12-x86_64.tar.xz
tar xf mysql-8.0.35-linux-glibc2.12-x86_64.tar.xz
ln -s mysql-8.0.35-linux-glibc2.12-x86_64 mysql

# 创建数据目录
mkdir -p /data/mysql/{data,binlog,tmp,relaylog}
chown -R mysql:mysql /data/mysql /usr/local/mysql

# 初始化实例
/usr/local/mysql/bin/mysqld --initialize-insecure --user=mysql \
  --basedir=/usr/local/mysql \
  --datadir=/data/mysql/data \
  --socket=/tmp/mysql.sock \
  --log-error=/data/mysql/mysql.err
```

### 2.3 启动与 systemd 配置

创建 `/etc/systemd/system/mysql.service`：

```ini
[Unit]
Description=MySQL 8.0.35 Database Server
After=network.target

[Service]
Type=forking
User=mysql
Group=mysql
ExecStart=/usr/local/mysql/bin/mysqld --defaults-file=/etc/my.cnf --daemonize
ExecStop=/usr/local/mysql/bin/mysqladmin -u root -p shutdown
PIDFile=/data/mysql/mysqld.pid
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable mysql
systemctl start mysql
```

---

## 3. 配置规范

### 3.1 主配置文件 `/etc/my.cnf`

以下为生产环境 16C / 64G RAM 服务器的标准模板，其他规格按比例调整。

```ini
[client]
port = 3306
socket = /tmp/mysql.sock

[mysqld]
# 基础设置
user = mysql
port = 3306
basedir = /usr/local/mysql
datadir = /data/mysql/data
socket = /tmp/mysql.sock
pid-file = /data/mysql/mysqld.pid
log-error = /data/mysql/mysql.err

# 字符集与排序
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
init-connect = 'SET NAMES utf8mb4'

# 连接设置
max_connections = 500
max_connect_errors = 10000
wait_timeout = 1800
interactive_timeout = 1800

# 缓冲池设置（建议值为物理内存的 60%-70%）
innodb_buffer_pool_size = 40G
innodb_buffer_pool_instances = 8
innodb_log_file_size = 4G
innodb_log_files_in_group = 3
innodb_flush_log_at_trx_commit = 1

# 双写缓冲（生产环境关闭，依赖 SSD 的原子写）
innodb_doublewrite = OFF

# 临时表与排序
tmp_table_size = 64M
max_heap_table_size = 64M
sort_buffer_size = 2M
join_buffer_size = 2M

# 日志与复制
server-id = 10001                     # 每台服务器唯一
log-bin = /data/mysql/binlog/mysql-bin
binlog_format = ROW
binlog_row_image = FULL
expire_logs_days = 7
max_binlog_size = 512M
sync_binlog = 1
relay_log = /data/mysql/relaylog/mysql-relay
log_slave_updates = ON
gtid_mode = ON
enforce_gtid_consistency = ON

# 错误日志
log_error_verbosity = 3
slow_query_log = ON
slow_query_log_file = /data/mysql/slow.log
long_query_time = 2
log_queries_not_using_indexes = ON

# 安全设置
skip_name_resolve
skip_symbolic_links
symbolic_links = 0
local_infile = OFF
```

### 3.2 参数模板矩阵

| 环境类型       | 物理内存 | innodb_buffer_pool_size | max_connections | 双写缓冲 | 慢查询阈值 |
|----------------|----------|--------------------------|-----------------|----------|------------|
| 生产（高负载） | 64G      | 40G                      | 800             | OFF      | 1s         |
| 生产（中负载） | 32G      | 20G                      | 500             | OFF      | 2s         |
| 测试           | 16G      | 8G                       | 200             | ON       | 5s         |
| 预发布         | 32G      | 20G                      | 300             | OFF      | 2s         |

---

## 4. 初始化与安全加固

### 4.1 首次登录与密码设置

```sql
-- 初始无密码，登录后立即修改
ALTER USER 'root'@'localhost' IDENTIFIED BY 'YourStrongP@ssw0rd!';
FLUSH PRIVILEGES;
```

### 4.2 创建业务用户

```sql
-- 使用强密码，禁止使用默认密码
CREATE USER 'app_user'@'10.0.%.%' IDENTIFIED BY 'B1z@pp_2024!Secure';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX ON `business_db`.* TO 'app_user'@'10.0.%.%';
FLUSH PRIVILEGES;
```

### 4.3 删除默认用户与测试库

```sql
DROP USER IF EXISTS 'root'@'::1';
DROP USER IF EXISTS 'mysql.sys'@'localhost';
DROP DATABASE IF EXISTS test;
```

---

## 5. 备份策略

### 5.1 备份计划

| 备份类型 | 频率       | 工具        | 保留周期 | 存储位置                |
|----------|------------|-------------|----------|-------------------------|
| 全量备份 | 每日 01:00 | XtraBackup  | 7 天     | /backup/mysql/full/     |
| 增量备份 | 每 4 小时  | XtraBackup  | 48 小时  | /backup/mysql/incr/     |
| Binlog   | 实时       | 系统rsync   | 7 天     | /backup/mysql/binlog/   |

### 5.2 全量备份脚本示例

```bash
#!/bin/bash
# /usr/local/bin/xtrabackup_full.sh

BACKUP_DIR="/backup/mysql/full/$(date +%Y%m%d_%H%M%S)"
USER="backup