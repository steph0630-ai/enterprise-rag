"""测试 SQLExecutor — 安全执行、拦截危险操作"""

import os
import sqlite3

import pytest
from app.nl2sql.sql_executor import SQLExecutor


class TestSQLExecutor:
    """SQL 执行器安全测试"""

    def test_execute_valid_select(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("SELECT COUNT(*) as cnt FROM orders")
        assert result.success
        assert result.row_count == 1
        assert result.columns == ["cnt"]
        # Brazilian E-Commerce has ~99k orders

    def test_execute_with_aggregation(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute(
            "SELECT order_status, COUNT(*) as total "
            "FROM orders GROUP BY order_status"
        )
        assert result.success
        assert result.row_count > 0
        assert "order_status" in result.columns
        assert "total" in result.columns

    def test_execute_with_order_limit(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute(
            "SELECT product_id, price FROM order_items ORDER BY price DESC LIMIT 3"
        )
        assert result.success
        assert result.row_count == 3

    # ── 安全拦截测试 ──

    def test_reject_drop(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("DROP TABLE orders")
        assert not result.success
        # DROP 可能被 "仅允许 SELECT" 拦截，也可能被 "禁止的操作: DROP" 拦截
        assert ("禁止" in result.error or "允许 SELECT" in result.error
                or "DROP" in result.error.upper())

    def test_reject_delete(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("DELETE FROM orders WHERE order_id = 'test'")
        assert not result.success

    def test_reject_insert(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute(
            "INSERT INTO orders (order_id, order_status) VALUES ('1', 'test')"
        )
        assert not result.success

    def test_reject_update(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("UPDATE orders SET order_status = 'hacked'")
        assert not result.success

    def test_reject_alter(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("ALTER TABLE orders ADD COLUMN hacked TEXT")
        assert not result.success

    def test_reject_pragma(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("PRAGMA journal_mode=DELETE")
        assert not result.success

    def test_reject_non_select_prefix(self, sample_db_path):
        """不以 SELECT 开头的语句直接拒绝"""
        executor = SQLExecutor(sample_db_path)
        result = executor.execute("  DELETE FROM orders")
        assert not result.success

    # ── 结果截断测试 ──

    def test_row_limit(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        executor.MAX_ROWS = 3  # 临时降低上限
        result = executor.execute("SELECT * FROM order_items")
        assert result.success
        assert result.truncated
        assert result.row_count == 3

    # ── 空结果 ──

    def test_empty_result(self, sample_db_path):
        executor = SQLExecutor(sample_db_path)
        result = executor.execute(
            "SELECT * FROM orders WHERE order_id = 'nonexistent_id'"
        )
        assert result.success
        assert result.row_count == 0
        assert result.rows == []

    # ── 临时数据库测试（不依赖真实数据） ──

    def test_with_temp_database(self, temp_db_path):
        """在临时数据库上建表 → 查询 → 验证"""
        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello'), (2, 'world')")
        conn.commit()
        conn.close()

        executor = SQLExecutor(temp_db_path)
        result = executor.execute("SELECT * FROM test ORDER BY id")
        assert result.success
        assert result.row_count == 2
        assert result.rows == [["1", "hello"], ["2", "world"]]
