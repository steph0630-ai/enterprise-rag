"""NL2SQL 全链路编排 — Intent Router → SQL Gen → Execute → Natural Language Answer

这是 NL2SQL 的"Generator"等价物，类似于 RAG 的 generator.py。
"""

import logging
from dataclasses import dataclass, field

from app.core.llm import LLMClient
from app.nl2sql.intent_router import IntentRouter
from app.nl2sql.schema_manager import SchemaManager
from app.nl2sql.sql_generator import SQLGenerator
from app.nl2sql.sql_executor import SQLExecutor, get_executor
from app.generation.prompts import NL2SQL_ANSWER_PROMPT, NL2SQL_FALLBACK_ANSWER

logger = logging.getLogger(__name__)


@dataclass
class NL2SQLAnswer:
    """NL2SQL 回答"""
    answer: str
    intent: str  # "sql" | "rag"
    sql: str | None = None
    sql_explanation: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0
    error: str = ""


class NL2SQLPipeline:
    """编排 NL2SQL 完整链路：路由 → 生成SQL → 执行 → 自然语言回答"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.schema_manager = SchemaManager(db_path)
        self.executor = get_executor(db_path) or SQLExecutor(db_path)
        self.sql_generator = SQLGenerator(self.schema_manager, self.executor)
        self.router = IntentRouter(self.schema_manager)
        self.llm = LLMClient()

    def answer(self, query: str, max_rows: int = 200) -> NL2SQLAnswer:
        """执行 NL2SQL 全链路，返回自然语言回答"""
        # Step 1: SQL 生成 + 执行
        result = self.sql_generator.generate_and_execute(query)

        if not result["success"]:
            return NL2SQLAnswer(
                answer=f"无法完成数据查询：{result['error']}",
                intent="sql",
                sql=result.get("sql"),
                sql_explanation=result.get("sql_explanation", ""),
                error=result["error"],
            )

        # Step 2: 将 SQL 结果转为自然语言
        sql = result["sql"]
        columns = result["columns"]
        rows = result["rows"]
        row_count = result["row_count"]
        truncated = result["truncated"]
        exec_time = result["execution_time_ms"]

        # 构建结果摘要
        result_summary = self._format_result_summary(columns, rows, row_count, truncated, max_rows)

        # Step 3: LLM 生成自然语言回答
        try:
            answer_text = self.llm.chat([
                {
                    "role": "user",
                    "content": NL2SQL_ANSWER_PROMPT.format(
                        query=query,
                        sql=sql,
                        result_summary=result_summary,
                        max_rows=max_rows,
                    ),
                }
            ])
        except Exception as e:
            logger.error("NL2SQL answer generation failed: %s", e)
            # 回退：直接用模板格式化
            answer_text = self._fallback_format(
                result["sql_explanation"], sql, columns, rows,
                row_count, truncated, exec_time,
            )

        return NL2SQLAnswer(
            answer=answer_text,
            intent="sql",
            sql=sql,
            sql_explanation=result["sql_explanation"],
            columns=columns,
            rows=rows,
            row_count=row_count,
            truncated=truncated,
            execution_time_ms=exec_time,
        )

    def _format_result_summary(
        self, columns: list[str], rows: list[list],
        row_count: int, truncated: bool, max_rows: int,
    ) -> str:
        """构建 LLM 友好的结果摘要"""
        if not rows:
            return "（查询结果为空）"

        # 列名
        header = " | ".join(columns)
        lines = [header, "-" * len(header)]

        # 数据行（最多展示 20 行给 LLM，超过会截断）
        for row in rows[:20]:
            lines.append(" | ".join(str(v) for v in row))

        result = "\n".join(lines)

        if truncated:
            result += f"\n\n（结果被截断，实际返回了 {row_count} 行，上限 {max_rows} 行）"

        return result

    def _fallback_format(
        self, explanation: str, sql: str,
        columns: list[str], rows: list[list],
        row_count: int, truncated: bool, exec_time: float,
    ) -> str:
        """当 LLM 生成失败时的回退格式化"""
        if not columns:
            return f"查询完成。{explanation}"

        truncated_note = f"结果超过上限，仅展示前 {len(rows)} 行" if truncated else ""
        return NL2SQL_FALLBACK_ANSWER.format(
            explanation=explanation,
            sql=sql,
            execution_time=exec_time,
            row_count=row_count,
            columns_header=" | ".join(columns),
            rows_md="\n".join(
                " | ".join(str(v) for v in row) for row in rows
            ),
            truncated_note=truncated_note,
        )

    def route_only(self, query: str) -> dict:
        """仅做意图路由，不执行查询"""
        return self.router.route(query)
