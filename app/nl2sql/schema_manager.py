"""数据库 Schema 管理 — 从 SQLite 提取表结构和示例数据，用于生成 SQL 的 Prompt"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    sample_values: list[str] = field(default_factory=list)


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    row_count: int = 0
    sample_rows: list[dict] = field(default_factory=list)


class SchemaManager:
    """读取 SQLite 数据库结构，生成 LLM 友好的 schema 描述"""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_tables(self) -> list[str]:
        """获取所有表名"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        return [r["name"] for r in rows]

    def get_table_info(self, table_name: str, sample_rows: int = 5) -> TableInfo:
        """获取单张表的详细信息"""
        with self._connect() as conn:
            # 列信息
            pragma = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            columns = [
                ColumnInfo(
                    name=row["name"],
                    type=row["type"],
                    nullable=not bool(row["notnull"]),
                )
                for row in pragma
            ]

            # 行数
            row_count = conn.execute(f"SELECT COUNT(*) as cnt FROM '{table_name}'").fetchone()["cnt"]

            # 采样数据
            samples = conn.execute(f"SELECT * FROM '{table_name}' LIMIT {sample_rows}").fetchall()
            sample_rows_list = [dict(s) for s in samples]

            # 每列的采样值
            for col in columns:
                col.sample_values = [
                    str(row[col.name]) for row in samples if row[col.name] is not None
                ][:3]

        return TableInfo(
            name=table_name,
            columns=columns,
            row_count=row_count,
            sample_rows=sample_rows_list,
        )

    def get_schema_text(self) -> str:
        """生成 LLM prompt 中使用的 schema 描述文本"""
        tables = self.get_tables()
        parts = []

        for table_name in tables:
            info = self.get_table_info(table_name, sample_rows=3)
            cols_desc = []
            for col in info.columns:
                samples_str = f"  示例: {', '.join(col.sample_values)}" if col.sample_values else ""
                nullable = " 可为空" if col.nullable else ""
                cols_desc.append(f"    - {col.name} ({col.type}){nullable}{samples_str}")

            parts.append(
                f"""### 表名: {table_name} (共 {info.row_count} 行)

列定义:
{chr(10).join(cols_desc)}

前 3 行数据:
{self._format_sample_rows(info.sample_rows)}
"""
            )

        return "\n".join(parts)

    def _format_sample_rows(self, rows: list[dict]) -> str:
        if not rows:
            return "  (空表)"
        lines = []
        for i, row in enumerate(rows):
            line = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"  Row {i+1}: {line}")
        return "\n".join(lines)

    def validate_sql(self, sql: str) -> tuple[bool, str]:
        """用 EXPLAIN 验证 SQL 语法是否正确，不实际执行"""
        try:
            with self._connect() as conn:
                conn.execute(f"EXPLAIN {sql}")
            return True, ""
        except sqlite3.Error as e:
            return False, str(e)
