"""SQL 安全执行器 — 只允许 SELECT，含超时、行数限制、危险操作拦截"""

import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 危险操作的 SQL 关键词（禁止执行）
FORBIDDEN_PATTERNS = [
    r"\bDROP\b",
    r"\bDELETE\b",
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bREPLACE\b",
    r"\bTRUNCATE\b",
    r"\bATTACH\b",
    r"\bDETACH\b",
    r"\bPRAGMA\b",
    r"\bVACUUM\b",
    r"\bREINDEX\b",
]


@dataclass
class SQLResult:
    """SQL 执行结果"""
    success: bool
    columns: list[str]
    rows: list[list]
    row_count: int
    sql: str
    error: str = ""
    truncated: bool = False  # 结果是否被截断
    execution_time_ms: float = 0


class SQLExecutor:
    """安全的 SQL 执行器

    安全措施：
    1. 正则拦截危险操作（只允许 SELECT）
    2. 只读连接（readonly=True 在 WAL 模式下仍然允许读）
    3. 最大行数限制（默认 200 行）
    4. 查询超时（默认 10 秒）
    5. 结果集大小限制
    """

    MAX_ROWS = 200
    TIMEOUT_SECONDS = 10

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def execute(self, sql: str) -> SQLResult:
        """执行 SQL 查询，返回结构化结果"""
        import time

        # 1. 安全检查
        ok, err = self._security_check(sql)
        if not ok:
            return SQLResult(success=False, columns=[], rows=[], row_count=0, sql=sql, error=err)

        # 2. 执行（带超时）
        start = time.time()
        result_container: list[SQLResult] = []
        error_container: list[Exception] = []

        def _run():
            try:
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(sql)
                columns = [d[0] for d in cursor.description] if cursor.description else []
                rows = []
                for i, row in enumerate(cursor):
                    if len(rows) >= self.MAX_ROWS:
                        result_container.append(SQLResult(
                            success=True, columns=columns, rows=rows,
                            row_count=len(rows), sql=sql, truncated=True,
                            execution_time_ms=(time.time() - start) * 1000,
                        ))
                        conn.close()
                        return
                    rows.append([self._serialize(v) for v in row])
                conn.close()
                result_container.append(SQLResult(
                    success=True, columns=columns, rows=rows,
                    row_count=len(rows), sql=sql,
                    execution_time_ms=(time.time() - start) * 1000,
                ))
            except Exception as e:
                error_container.append(e)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=self.TIMEOUT_SECONDS)

        if thread.is_alive():
            return SQLResult(
                success=False, columns=[], rows=[], row_count=0, sql=sql,
                error=f"查询超时（超过 {self.TIMEOUT_SECONDS} 秒）",
            )

        if error_container:
            return SQLResult(
                success=False, columns=[], rows=[], row_count=0, sql=sql,
                error=f"执行错误: {error_container[0]}",
            )

        return result_container[0] if result_container else SQLResult(
            success=False, columns=[], rows=[], row_count=0, sql=sql, error="未知错误",
        )

    def _security_check(self, sql: str) -> tuple[bool, str]:
        """安全检查：只允许 SELECT 语句"""
        sql_upper = sql.strip().upper()

        # 必须以 SELECT 开头（允许 WITH/EXPLAIN 前缀的 SELECT）
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH") or sql_upper.startswith("EXPLAIN")):
            return False, "仅允许 SELECT 查询语句"

        # 检测危险关键词
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, sql_upper):
                clean_pattern = pattern.replace(r'\b', '')
                return False, f"SQL 中包含禁止的操作: {clean_pattern}"

        return True, ""

    @staticmethod
    def _serialize(value) -> str:
        """将 Python 值转为可序列化的字符串"""
        if value is None:
            return "NULL"
        if isinstance(value, float):
            return f"{value:.2f}" if value == int(value) else str(value)
        return str(value)


# ── 方便获取单例的函数 ──

_executor: SQLExecutor | None = None


def get_executor(db_path: str | Path | None = None) -> SQLExecutor:
    global _executor
    if _executor is None and db_path:
        _executor = SQLExecutor(db_path)
    return _executor


def reset_executor():
    global _executor
    _executor = None
