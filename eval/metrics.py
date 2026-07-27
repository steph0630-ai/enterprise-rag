"""评测指标计算 — Recall, Faithfulness, Hallucination Detection, SQL Accuracy"""

import re
from dataclasses import dataclass, field


@dataclass
class RAGEvalResult:
    """单条 RAG 评测结果"""
    query_id: str
    query: str
    intent_correct: bool
    actual_intent: str
    # 检索指标
    recall_hit: int = 0   # 命中的关键词数量
    recall_total: int = 0  # 期望的关键词数量
    recall_score: float = 0.0
    # 生成指标
    contains_required: int = 0
    contains_forbidden: int = 0
    faithfulness_score: float = 0.0
    # 汇总
    passed: bool = False
    notes: str = ""


@dataclass
class NL2SQLEvalResult:
    """单条 NL2SQL 评测结果"""
    query_id: str
    query: str
    intent_correct: bool
    actual_intent: str
    # SQL 质量
    sql_generated: str | None = None
    sql_keywords_hit: int = 0
    sql_keywords_total: int = 0
    sql_valid: bool = False
    sql_executed: bool = False
    # 答案质量
    answer_contains_hit: int = 0
    answer_contains_total: int = 0
    # 汇总
    passed: bool = False
    notes: str = ""


@dataclass
class EvalReport:
    """评测报告"""
    total: int
    passed: int
    pass_rate: float
    intent_accuracy: float
    rag_results: list[RAGEvalResult] = field(default_factory=list)
    sql_results: list[NL2SQLEvalResult] = field(default_factory=list)
    # 汇总指标
    avg_rag_recall: float = 0.0
    avg_rag_faithfulness: float = 0.0
    avg_sql_keyword_hit_rate: float = 0.0
    avg_sql_answer_hit_rate: float = 0.0


def evaluate_rag(query_id: str, query: str, expected_intent: str,
                 actual_intent: str, context_chunks: list[str],
                 expected_chunks: list[str], answer: str,
                 must_contain: list[str], must_not_contain: list[str]) -> RAGEvalResult:
    """评测单条 RAG 回答"""

    intent_correct = actual_intent == expected_intent

    # 检索命中率：检查期望的关键词在检索到的 chunk 中出现了多少
    context_text = " ".join(context_chunks).lower()
    recall_hit = sum(1 for kw in expected_chunks if kw.lower() in context_text)
    recall_total = len(expected_chunks)
    recall_score = recall_hit / recall_total if recall_total > 0 else 1.0

    # 答案包含检查
    answer_lower = answer.lower()
    contains_required = sum(1 for kw in must_contain if kw.lower() in answer_lower)
    contains_forbidden = sum(1 for kw in must_not_contain if kw.lower() in answer_lower)

    # 忠实度：必含关键词命中率 - 禁止关键词惩罚
    req_score = contains_required / len(must_contain) if must_contain else 1.0
    forbidden_penalty = 1.0 if contains_forbidden > 0 else 0.0
    faithfulness_score = max(0.0, req_score - forbidden_penalty)

    passed = intent_correct and recall_score >= 0.5 and faithfulness_score >= 0.5

    return RAGEvalResult(
        query_id=query_id,
        query=query,
        intent_correct=intent_correct,
        actual_intent=actual_intent,
        recall_hit=recall_hit,
        recall_total=recall_total,
        recall_score=recall_score,
        contains_required=contains_required,
        contains_forbidden=contains_forbidden,
        faithfulness_score=faithfulness_score,
        passed=passed,
        notes=_build_rag_notes(intent_correct, recall_score, faithfulness_score),
    )


def evaluate_nl2sql(query_id: str, query: str, expected_intent: str,
                    actual_intent: str, sql: str | None,
                    expected_sql_keywords: list[str],
                    sql_executed: bool, answer: str,
                    expected_answer_contains: list[str]) -> NL2SQLEvalResult:
    """评测单条 NL2SQL 回答"""

    intent_correct = actual_intent == expected_intent

    # SQL 关键词命中
    sql_hit = 0
    if sql:
        sql_upper = sql.upper()
        sql_hit = sum(1 for kw in expected_sql_keywords if kw.upper() in sql_upper)
    sql_total = len(expected_sql_keywords)

    # SQL 有效性
    sql_valid = sql is not None
    sql_ok = sql_valid and sql_executed

    # 答案内容检查（去除逗号和空格以兼容数字格式差异）
    answer_normalized = answer.lower().replace(",", "").replace("，", "").replace(" ", "")
    answer_hit = sum(1 for kw in expected_answer_contains
                     if kw.lower().replace(",", "").replace("，", "").replace(" ", "") in answer_normalized)
    answer_total = len(expected_answer_contains)

    passed = intent_correct and sql_ok and answer_hit >= 1

    return NL2SQLEvalResult(
        query_id=query_id,
        query=query,
        intent_correct=intent_correct,
        actual_intent=actual_intent,
        sql_generated=sql,
        sql_keywords_hit=sql_hit,
        sql_keywords_total=sql_total,
        sql_valid=sql_valid,
        sql_executed=sql_executed,
        answer_contains_hit=answer_hit,
        answer_contains_total=answer_total,
        passed=passed,
        notes=_build_sql_notes(intent_correct, sql_ok, sql_hit, sql_total, answer_hit, answer_total),
    )


def generate_report(rag_results: list[RAGEvalResult],
                    sql_results: list[NL2SQLEvalResult]) -> EvalReport:
    """生成汇总评测报告"""
    all_results = rag_results + sql_results
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    intent_correct = sum(1 for r in all_results if r.intent_correct)

    report = EvalReport(
        total=total,
        passed=passed,
        pass_rate=passed / total if total > 0 else 0.0,
        intent_accuracy=intent_correct / total if total > 0 else 0.0,
        rag_results=rag_results,
        sql_results=sql_results,
    )

    # RAG 汇总
    if rag_results:
        report.avg_rag_recall = sum(r.recall_score for r in rag_results) / len(rag_results)
        report.avg_rag_faithfulness = sum(r.faithfulness_score for r in rag_results) / len(rag_results)

    # NL2SQL 汇总
    if sql_results:
        report.avg_sql_keyword_hit_rate = (
            sum(r.sql_keywords_hit for r in sql_results) /
            max(1, sum(r.sql_keywords_total for r in sql_results))
        )
        report.avg_sql_answer_hit_rate = (
            sum(r.answer_contains_hit for r in sql_results) /
            max(1, sum(r.answer_contains_total for r in sql_results))
        )

    return report


def format_report(report: EvalReport) -> str:
    """格式化评测报告为 Markdown"""
    lines = [
        "# 评测报告",
        "",
        "## 总览",
        f"| 指标 | 值 |",
        f"|---|---|",
        f"| 总样本数 | {report.total} |",
        f"| 通过数 | {report.passed} |",
        f"| 通过率 | {report.pass_rate:.1%} |",
        f"| 意图分类准确率 | {report.intent_accuracy:.1%} |",
        "",
    ]

    if report.rag_results:
        lines += [
            "## RAG 评测",
            f"| 指标 | 值 |",
            f"|---|---|",
            f"| 平均召回率 | {report.avg_rag_recall:.1%} |",
            f"| 平均忠实度 | {report.avg_rag_faithfulness:.1%} |",
            "",
            "### 明细",
            "",
            "| ID | Query | Intent Correct | Recall | Faithfulness | Passed |",
            "|---|---|---|---|---|---|",
        ]
        for r in report.rag_results:
            lines.append(
                f"| {r.query_id} | {r.query[:30]} | {r.intent_correct} | "
                f"{r.recall_score:.2f} | {r.faithfulness_score:.2f} | {r.passed} |"
            )
        lines.append("")

    if report.sql_results:
        lines += [
            "## NL2SQL 评测",
            f"| 指标 | 值 |",
            f"|---|---|",
            f"| SQL 关键词命中率 | {report.avg_sql_keyword_hit_rate:.1%} |",
            f"| 答案内容命中率 | {report.avg_sql_answer_hit_rate:.1%} |",
            "",
            "### 明细",
            "",
            "| ID | Query | Intent Correct | SQL Valid | Keywords | Answer Hit | Passed |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in report.sql_results:
            lines.append(
                f"| {r.query_id} | {r.query[:30]} | {r.intent_correct} | "
                f"{r.sql_valid} | {r.sql_keywords_hit}/{r.sql_keywords_total} | "
                f"{r.answer_contains_hit}/{r.answer_contains_total} | {r.passed} |"
            )
        lines.append("")

    # 未通过的项
    failed = [r for r in report.rag_results + report.sql_results if not r.passed]
    if failed:
        lines += ["## 未通过项", ""]
        for r in failed:
            lines.append(f"- **{r.query_id}**: {r.notes}")

    return "\n".join(lines)


# ── helpers ──

def _build_rag_notes(intent_ok: bool, recall: float, faithfulness: float) -> str:
    parts = []
    if not intent_ok:
        parts.append("意图分类错误")
    if recall < 0.5:
        parts.append(f"召回率过低({recall:.0%})")
    if faithfulness < 0.5:
        parts.append(f"忠实度过低({faithfulness:.0%})")
    return "; ".join(parts) if parts else "OK"


def _build_sql_notes(intent_ok: bool, sql_ok: bool,
                     sql_hit: int, sql_total: int,
                     ans_hit: int, ans_total: int) -> str:
    parts = []
    if not intent_ok:
        parts.append("意图分类错误")
    if not sql_ok:
        parts.append("SQL 生成/执行失败")
    if sql_hit < sql_total:
        parts.append(f"SQL 关键词命中不足({sql_hit}/{sql_total})")
    if ans_hit == 0:
        parts.append(f"答案未包含期望信息(0/{ans_total})")
    return "; ".join(parts) if parts else "OK"
