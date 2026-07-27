# SQL 编写规范与慢查询优化指南

| 文档编号 | TECH-SQL-2024-001 |
|--------|------------------|
| 版本号 | v1.3 |
| 生效日期 | 2024-04-01 |
| 负责人 | 李振宇（数据库团队） |
| 审核人 | 王敏（架构组） |

## 变更记录

| 版本 | 日期 | 变更内容 | 修订人 |
|------|------|----------|--------|
| v1.0 | 2023-06-15 | 初始版本 | 李振宇 |
| v1.1 | 2023-09-20 | 增加索引优化章节 | 陈晓峰 |
| v1.2 | 2024-01-10 | 补充分页优化规范 | 李振宇 |
| v1.3 | 2024-04-01 | 新增慢查询日志配置示例 | 张思远 |

---

## 1. 通用编写规范

### 1.1 命名规范

- **表名、字段名**：使用小写字母和下划线 `snake_case`，禁止使用保留字或数字开头。
- **索引命名**：主键 `pk_表名`，唯一索引 `uk_字段名`，普通索引 `idx_字段名`。
- **临时表**：前缀加 `tmp_`，并在使用后及时删除。

### 1.2 格式要求

- **关键字**统一大写，例如 `SELECT`、`FROM`、`WHERE`。
- **子查询**必须缩进，`JOIN` 条件显式写在 `ON` 子句中，禁止隐式 `WHERE` 连接。
- **每行**不超过 120 字符，过长时换行并对齐。

示例：

```sql
SELECT
    u.id,
    u.name,
    o.order_amount
FROM
    user u
    INNER JOIN order o ON u.id = o.user_id
WHERE
    u.status = 'active'
    AND o.created_at >= '2024-01-01'
ORDER BY
    o.created_at DESC;
```

---

## 2. 查询性能规范

### 2.1 避免 `SELECT *`

- 必须明确列出需要的字段，禁止使用 `SELECT *`。
- 理由：减少数据传输量，避免 `covering index` 失效。

错误示例：

```sql
SELECT * FROM order WHERE user_id = 123;
```

正确示例：

```sql
SELECT id, order_amount, status FROM order WHERE user_id = 123;
```

### 2.2 合理使用 `JOIN`

- 多表 `JOIN` 不超过 3 张表。
- `JOIN` 字段必须建立索引，类型必须一致（如 `INT` 对 `INT`）。
- 避免 `LEFT JOIN` 被错误使用，优先使用 `INNER JOIN`。

### 2.3 分页优化

- 禁止使用 `OFFSET` 大偏移量分页（如 `LIMIT 100000, 20`）。
- 推荐使用 **Keyset Pagination**（基于游标分页）：

```sql
-- 传统方式（不推荐）
SELECT id, name FROM user ORDER BY id LIMIT 20 OFFSET 100000;

-- 游标方式（推荐）
SELECT id, name FROM user WHERE id > 100000 ORDER BY id LIMIT 20;
```

---

## 3. 索引设计规范

### 3.1 索引创建原则

- **区分度高的列**优先作为索引前缀。
- **联合索引**遵循“最左前缀”原则，将等值条件列放在前面。
- 索引数量**不超过 5 个**，避免写性能下降。

### 3.2 避免索引失效

- 不在索引列上使用函数或计算。
- 避免隐式类型转换（如 `WHERE phone = 13800138000`，phone 为 `VARCHAR` 类型）。

错误示例：

```sql
SELECT * FROM user WHERE DATE(created_at) = '2024-01-01';
```

正确示例：

```sql
SELECT * FROM user WHERE created_at >= '2024-01-01' AND created_at < '2024-01-02';
```

---

## 4. 慢查询优化流程

### 4.1 启用慢查询日志

MySQL 配置示例（`my.cnf`）：

```ini
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow-query.log
long_query_time = 2
log_queries_not_using_indexes = 1
```

### 4.2 分析慢查询

使用 `EXPLAIN` 命令分析执行计划：

```sql
EXPLAIN SELECT * FROM order WHERE user_id = 123 AND status = 'paid'\G
```

关键指标：
- `type`：至少为 `range`，最好为 `ref` 或 `const`。
- `rows`：扫描行数应远小于表总行数。
- `Extra`：避免出现 `Using filesort`、`Using temporary`。

### 4.3 常见优化手段

| 场景 | 优化策略 |
|------|----------|
| 全表扫描 | 增加合适索引 |
| 文件排序 | 为 `ORDER BY` 字段建立索引 |
| 临时表 | 减少 `GROUP BY` 或 `DISTINCT` 使用，或优化索引 |
| 大表分页 | 改用游标分页 |

---

## 5. 示例：慢查询优化实战

### 5.1 问题 SQL

```sql
SELECT
    u.name,
    COUNT(o.id) AS order_count
FROM
    user u
    LEFT JOIN order o ON u.id = o.user_id
WHERE
    u.status = 'active'
GROUP BY
    u.id
HAVING
    order_count > 5;
```

### 5.2 `EXPLAIN` 分析

```
+----+-------------+-------+------+---------------+------+---------+------+------+----------------------------------------------+
| id | select_type | table | type | possible_keys | key  | key_len | ref  | rows | Extra                                        |
+----+-------------+-------+------+---------------+------+---------+------+------+----------------------------------------------+
|  1 | SIMPLE      | u     | ALL  | NULL          | NULL | NULL    | NULL | 100K | Using where; Using temporary; Using filesort |
|  1 | SIMPLE      | o     | ALL  | NULL          | NULL | NULL    | NULL | 500K | Using where; Using join buffer                |
+----+-------------+-------+------+---------------+------+---------+------+------+----------------------------------------------+
```

问题：全表扫描、临时表、文件排序。

### 5.3 优化方案

1. 在 `user.status` 和 `order.user_id` 上建立索引：

```sql
CREATE INDEX idx_user_status ON user(status);
CREATE INDEX idx_order_user_id ON order(user_id);
```

2. 改写为子查询方式，减少 `LEFT JOIN` 带来的扫描：

```sql
SELECT
    u.name,
    (SELECT COUNT(*) FROM order o WHERE o.user_id = u.id) AS order_count
FROM
    user u
WHERE
    u.status = 'active'
    AND EXISTS (SELECT 1 FROM order o WHERE o.user_id = u.id HAVING COUNT(*) > 5);
```

3. 重新 `EXPLAIN` 验证：

```
+----+--------------------+-------+------+-------------------+-------------------+---------+-----------+------+----------+
| id | select_type        | table | type | possible_keys     | key               | key_len | ref       | rows | Extra    |
+----+--------------------+-------+------+-------------------+-------------------+---------+-----------+------+----------+
|  1 | PRIMARY            | u     | ref  | idx_user_status   | idx_user_status   | 1       | const     | 10K  | Using where |
|  2 | DEPENDENT SUBQUERY | o     | ref  | idx_order_user_id | idx_order_user_id | 4       | test.u.id | 5    | Using index |
+----+--------------------+-------+------+-------------------+-------------------+---------+-----------+------+----------+
```

扫描行数从 600K 降至约 15K，性能提升 40 倍。

---

## 6. 附则

- 所有 SQL 上线前必须经过 `SQL Review` 工具扫描（如 `SQLE` 或 `Yearning`）。
- 新表设计需提交 DDL 评审，`ALTER TABLE` 操作需在业务低峰期执行。
- 本规范每季度更新一次，由数据库团队负责修订。