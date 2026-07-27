"""测试 SchemaManager — 数据库结构读取"""

import pytest
from app.nl2sql.schema_manager import SchemaManager, TableInfo, ColumnInfo


class TestSchemaManager:
    """Schema Manager 单元测试"""

    def test_get_tables(self, sample_db_path):
        sm = SchemaManager(sample_db_path)
        tables = sm.get_tables()
        assert "orders" in tables
        assert "customers" in tables
        assert "products" in tables
        assert "order_items" in tables
        assert "order_payments" in tables
        assert "order_reviews" in tables
        assert "sellers" in tables
        assert len(tables) == 8

    def test_get_table_info(self, sample_db_path):
        sm = SchemaManager(sample_db_path)
        info = sm.get_table_info("orders")
        assert isinstance(info, TableInfo)
        assert info.name == "orders"
        assert info.row_count > 90000  # ~99k orders
        assert len(info.columns) >= 5

        # 验证列信息
        col_names = [c.name for c in info.columns]
        assert "order_id" in col_names
        assert "order_status" in col_names
        assert "order_purchase_timestamp" in col_names

        # 验证采样数据
        assert len(info.sample_rows) >= 1

    def test_get_schema_text(self, sample_db_path):
        sm = SchemaManager(sample_db_path)
        text = sm.get_schema_text()
        assert "orders" in text
        assert "order_items" in text

    def test_validate_sql_valid(self, sample_db_path):
        sm = SchemaManager(sample_db_path)
        ok, err = sm.validate_sql("SELECT * FROM orders LIMIT 5")
        assert ok
        assert err == ""

    def test_validate_sql_invalid(self, sample_db_path):
        sm = SchemaManager(sample_db_path)
        ok, err = sm.validate_sql("SELECT * FROM nonexistent_table")
        assert not ok
        assert "no such table" in err.lower()

    def test_nonexistent_table_info(self, sample_db_path):
        """查询不存在的表应抛出异常"""
        sm = SchemaManager(sample_db_path)
        with pytest.raises(Exception):
            sm.get_table_info("nonexistent")
