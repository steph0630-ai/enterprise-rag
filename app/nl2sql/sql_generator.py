"""SQL 生成器 — 基于 Schema + 用户问题，用 LLM 生成 SQL"""

import json
import logging
import re

from app.core.llm import LLMClient
from app.nl2sql.schema_manager import SchemaManager
from app.nl2sql.sql_executor import SQLExecutor, SQLResult

logger = logging.getLogger(__name__)

SQL_GENERATION_PROMPT = """你是一个 SQL 查询专家。根据以下数据库 Schema 和用户问题，生成一个 SQLite 兼容的 SELECT 语句。

## 数据库 Schema

{schema}

## 重要规则

1. **只生成 SELECT 语句**，禁止任何 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE
2. 使用 SQLite 语法
3. 如果用户问"总销售额/总销量"，用 SUM() 聚合
4. 如果用户问"排名/最高/最低"，用 ORDER BY + LIMIT
5. 如果用户问"哪个类目/分类"，用 GROUP BY
6. 如果用户问"平均值"，用 AVG()
7. 如果用户问"数量/个数"，用 COUNT()
8. 日期筛选用 strftime() 或 LIKE
9. 模糊查询用 LIKE '%关键词%'
10. **LIMIT 不超过 100**，除非用户指定了更大的值

## 用户问题

{query}

## 输出格式（严格 JSON，不要输出其他内容）

{{
  "sql": "生成的SELECT语句",
  "explanation": "这个SQL做了什么，用中文简短说明"
}}

如果问题无法用 SQL 回答（数据库中不存在相关数据），返回：
{{
  "sql": null,
  "explanation": "无法回答的原因"
}}"""


class SQLGenerator:
    """基于 LLM 的 SQL 生成器"""

    def __init__(self, schema_manager: SchemaManager, sql_executor: SQLExecutor):
        self.schema_manager = schema_manager
        self.executor = sql_executor
        self.llm = LLMClient()

    def generate_and_execute(self, query: str) -> dict:
        """
        根据自然语言问题生成 SQL 并执行。

        Returns:
            {
                "success": bool,
                "sql": str | None,
                "sql_explanation": str,
                "columns": [...],
                "rows": [[...], ...],
                "row_count": int,
                "truncated": bool,
                "error": str,
                "execution_time_ms": float,
            }
        """
        # Step 1: 获取 schema
        try:
            schema_text = self.schema_manager.get_schema_text()
        except Exception as e:
            return self._error_result("无法读取数据库结构", str(e))

        # Step 2: LLM 生成 SQL
        sql, sql_explanation = self._generate_sql(query, schema_text)
        if sql is None:
            return self._error_result("SQL 生成失败", sql_explanation)

        # Step 3: 验证 SQL 语法
        ok, err = self.schema_manager.validate_sql(sql)
        if not ok:
            # 尝试修复：让 LLM 再生成一次
            logger.warning("SQL validation failed, retrying: %s", err)
            sql, sql_explanation = self._generate_sql(
                f"{query}\n\n注意：上一条 SQL 语法错误：{err}，请修正",
                schema_text,
            )
            if sql is None:
                return self._error_result("SQL 语法错误", err)

        # Step 4: 执行
        result = self.executor.execute(sql)

        return {
            "success": result.success,
            "sql": result.sql,
            "sql_explanation": sql_explanation,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "error": result.error,
            "execution_time_ms": result.execution_time_ms,
        }

    def _generate_sql(self, query: str, schema_text: str) -> tuple[str | None, str]:
        """调用 LLM 生成 SQL，含多重容错解析"""
        prompt = SQL_GENERATION_PROMPT.format(schema=schema_text, query=query)

        try:
            raw = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=800,
            )

            # 尝试 1: 直接解析 JSON
            try:
                clean = raw
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                result = json.loads(clean)
                return result.get("sql"), result.get("explanation", "")
            except (json.JSONDecodeError, ValueError):
                pass

            # 尝试 2: 从 markdown 代码块提取 SQL
            md_match = re.search(r"```(?:sql)?\s*\n?(SELECT[\s\S]*?)```", raw, re.IGNORECASE)
            if md_match:
                sql = md_match.group(1).strip()
                return sql, "从 markdown 代码块提取"

            # 尝试 3: 直接查找 SELECT 语句
            select_match = re.search(r"(SELECT[\s\S]*?)(?:;|\n\n|$)", raw, re.IGNORECASE)
            if select_match:
                sql = select_match.group(1).strip()
                if sql.upper().startswith("SELECT"):
                    return sql, "从响应文本中提取"

            # 全部失败
            logger.error("Failed to parse SQL from: %s", raw[:300])
            return None, f"LLM 返回格式异常: {raw[:200]}"

        except Exception as e:
            logger.error("SQL generation failed: %s", e)
            return None, str(e)

    @staticmethod
    def _error_result(reason: str, detail: str) -> dict:
        return {
            "success": False,
            "sql": None,
            "sql_explanation": reason,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "error": detail,
            "execution_time_ms": 0,
        }
