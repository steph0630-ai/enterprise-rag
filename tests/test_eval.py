"""测试评测模块 — 数据集和指标"""

import pytest
from eval.dataset import load_dataset, load_dataset_by_intent, get_dataset_stats, EvalQuery
from eval.metrics import (
    evaluate_rag, evaluate_nl2sql, generate_report, format_report,
)


class TestEvalDataset:
    """评测数据集测试"""

    def test_load_dataset(self):
        dataset = load_dataset()
        assert len(dataset) > 0
        assert all(isinstance(q, EvalQuery) for q in dataset)

    def test_load_by_intent(self):
        rag = load_dataset_by_intent("rag")
        sql = load_dataset_by_intent("sql")
        assert len(rag) > 0
        assert len(sql) > 0
        # 每条样本的 intent 应该匹配
        for q in rag:
            assert q.intent == "rag"
        for q in sql:
            assert q.intent == "sql"

    def test_get_stats(self):
        stats = get_dataset_stats()
        assert stats["total"] > 0
        assert "rag" in stats["by_intent"]
        assert "sql" in stats["by_intent"]
        assert stats["by_intent"]["rag"] + stats["by_intent"]["sql"] == stats["total"]

    def test_each_query_has_required_fields(self):
        """每条评测样本都有必要的字段"""
        for q in load_dataset():
            assert q.id
            assert q.query
            assert q.intent in ("rag", "sql")
            if q.intent == "rag":
                assert q.must_contain, f"RAG query {q.id} 缺少 must_contain"
            else:
                assert q.expected_sql_keywords, f"SQL query {q.id} 缺少 expected_sql_keywords"


class TestMetrics:
    """评测指标计算测试"""

    def test_evaluate_rag_perfect(self):
        """完美匹配的 RAG 回答"""
        result = evaluate_rag(
            query_id="test-001",
            query="test",
            expected_intent="rag",
            actual_intent="rag",
            context_chunks=["订单服务超时时间是 30 秒"],
            expected_chunks=["超时", "30"],
            answer="订单服务默认超时时间是 30 秒。",
            must_contain=["30", "秒"],
            must_not_contain=["无法找到"],
        )
        assert result.intent_correct
        assert result.recall_score == 1.0
        assert result.faithfulness_score == 1.0
        assert result.passed

    def test_evaluate_rag_wrong_intent(self):
        """意图分类错误"""
        result = evaluate_rag(
            query_id="test-002",
            query="test",
            expected_intent="rag",
            actual_intent="sql",
            context_chunks=[],
            expected_chunks=["x"],
            answer="",
            must_contain=["x"],
            must_not_contain=[],
        )
        assert not result.intent_correct
        assert not result.passed

    def test_evaluate_rag_forbidden_content(self):
        """包含禁止内容的 RAG 回答"""
        result = evaluate_rag(
            query_id="test-003",
            query="test",
            expected_intent="rag",
            actual_intent="rag",
            context_chunks=["文档片段内容"],
            expected_chunks=["文档"],
            answer="根据现有文档，我无法找到相关信息",
            must_contain=["30"],
            must_not_contain=["无法找到"],
        )
        assert result.contains_forbidden > 0
        assert result.faithfulness_score == 0.0  # 被惩罚

    def test_evaluate_nl2sql_perfect(self):
        """完美匹配的 NL2SQL 回答"""
        result = evaluate_nl2sql(
            query_id="test-004",
            query="test",
            expected_intent="sql",
            actual_intent="sql",
            sql="SELECT COUNT(*) FROM orders WHERE order_status = 'delivered'",
            expected_sql_keywords=["COUNT", "FROM", "WHERE"],
            sql_executed=True,
            answer="数码配件总销售额为 2,013,400 元",
            expected_answer_contains=["2013400"],
        )
        assert result.intent_correct
        assert result.sql_keywords_hit == 3
        assert result.sql_executed
        assert result.answer_contains_hit == 1
        assert result.passed

    def test_evaluate_nl2sql_bad_sql(self):
        """SQL 生成失败"""
        result = evaluate_nl2sql(
            query_id="test-005",
            query="test",
            expected_intent="sql",
            actual_intent="sql",
            sql=None,
            expected_sql_keywords=["SUM"],
            sql_executed=False,
            answer="无法完成查询",
            expected_answer_contains=["2013400"],
        )
        assert not result.sql_valid
        assert not result.passed

    def test_generate_report(self):
        """测试汇总报告生成"""
        rag = [
            evaluate_rag("r1", "q1", "rag", "rag", ["c1"], ["c1"], "a1", ["a1"], []),
        ]
        sql = [
            evaluate_nl2sql("s1", "q2", "sql", "sql", "SELECT 1", ["SELECT"], True, "a2", ["a2"]),
        ]
        report = generate_report(rag, sql)
        assert report.total == 2
        assert report.pass_rate >= 0.0
        assert report.intent_accuracy >= 0.0

    def test_format_report(self):
        """测试报告 Markdown 输出"""
        rag = []
        sql = [
            evaluate_nl2sql("s1", "q", "sql", "sql", "SELECT 1", ["SELECT"], True, "answer", ["answer"]),
        ]
        report = generate_report(rag, sql)
        md = format_report(report)
        assert "# 评测报告" in md
        assert "NL2SQL" in md
