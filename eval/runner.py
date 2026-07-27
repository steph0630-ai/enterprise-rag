"""评测运行器 — 执行完整评测流程并生成报告

用法:
    python eval/runner.py            # 运行完整评测
    python eval/runner.py --ci       # CI 模式：有失败则 exit(1)
    python eval/runner.py --output report.md  # 输出到文件
"""

import sys
from pathlib import Path

# 确保项目根在 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.dataset import load_dataset_by_intent, get_dataset_stats
from eval.metrics import (
    evaluate_rag, evaluate_nl2sql, generate_report, format_report,
    RAGEvalResult, NL2SQLEvalResult,
)


def run_rag_eval(query_id: str, query: str, query_obj,
                 generator, nl2sql_pipeline) -> RAGEvalResult:
    """执行单条 RAG 评测"""
    # 意图路由
    route = nl2sql_pipeline.route_only(query)
    actual_intent = route["intent"]

    if actual_intent != "rag":
        return RAGEvalResult(
            query_id=query_id, query=query,
            intent_correct=False, actual_intent=actual_intent,
            notes=f"意图分类错误：期望 rag，实际 {actual_intent}",
        )

    # 检索（不经过精排，测量原始召回率）
    try:
        results = generator.retriever.retrieve(query, top_k=10)
    except Exception as e:
        return RAGEvalResult(
            query_id=query_id, query=query,
            intent_correct=True, actual_intent=actual_intent,
            notes=f"检索失败: {e}",
        )

    context_chunks = [r["content"] for r in results]

    # 生成回答
    try:
        rag_answer = generator.answer(query)
        answer = rag_answer.answer
    except Exception as e:
        answer = f"[生成失败: {e}]"

    return evaluate_rag(
        query_id=query_id, query=query,
        expected_intent="rag", actual_intent=actual_intent,
        context_chunks=context_chunks,
        expected_chunks=query_obj.expected_chunks,
        answer=answer,
        must_contain=query_obj.must_contain,
        must_not_contain=query_obj.must_not_contain,
    )


def run_sql_eval(query_id: str, query: str, query_obj,
                 nl2sql_pipeline) -> NL2SQLEvalResult:
    """执行单条 NL2SQL 评测"""
    route = nl2sql_pipeline.route_only(query)
    actual_intent = route["intent"]

    if actual_intent != "sql":
        return NL2SQLEvalResult(
            query_id=query_id, query=query,
            intent_correct=False, actual_intent=actual_intent,
            notes=f"意图分类错误：期望 sql，实际 {actual_intent}",
        )

    # 执行 NL2SQL
    result = nl2sql_pipeline.answer(query)

    return evaluate_nl2sql(
        query_id=query_id, query=query,
        expected_intent="sql", actual_intent=actual_intent,
        sql=result.sql,
        expected_sql_keywords=query_obj.expected_sql_keywords,
        sql_executed=result.row_count >= 0 and not result.error,
        answer=result.answer,
        expected_answer_contains=query_obj.expected_answer_contains,
    )


def main(ci_mode: bool = False, output_file: str | None = None):
    """运行评测主流程"""
    import time
    start = time.time()

    print("=" * 60)
    print("Enterprise RAG — 评测运行器")
    print("=" * 60)

    # 初始化
    print("\n[1/4] 初始化评测环境...")
    from app.generation.generator import Generator
    from app.nl2sql.pipeline import NL2SQLPipeline
    from app.config import PROJECT_ROOT

    generator = Generator(enable_rerank=False)  # 评测时不精排，减少 API 调用
    db_path = PROJECT_ROOT / "data" / "business.db"
    nl2sql = NL2SQLPipeline(str(db_path))

    # 数据集统计
    print("\n[2/4] 加载评测数据集...")
    stats = get_dataset_stats()
    print(f"  总样本: {stats['total']}")
    print(f"  RAG: {stats['by_intent']['rag']}, NL2SQL: {stats['by_intent']['sql']}")
    print(f"  难度: easy={stats['by_difficulty']['easy']}, "
          f"medium={stats['by_difficulty']['medium']}, hard={stats['by_difficulty']['hard']}")

    # 执行 RAG 评测
    print("\n[3/4] 执行评测...")
    rag_queries = load_dataset_by_intent("rag")
    sql_queries = load_dataset_by_intent("sql")

    rag_results = []
    for q in rag_queries:
        print(f"  RAG  [{q.id}] {q.query[:40]}...", end=" ")
        result = run_rag_eval(q.id, q.query, q, generator, nl2sql)
        rag_results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} (recall={result.recall_score:.0%}, faith={result.faithfulness_score:.0%})")

    sql_results = []
    for q in sql_queries:
        print(f"  SQL  [{q.id}] {q.query[:40]}...", end=" ")
        result = run_sql_eval(q.id, q.query, q, nl2sql)
        sql_results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} (intent_ok={result.intent_correct}, sql_ok={result.sql_executed})")

    # 生成报告
    print("\n[4/4] 生成评测报告...")
    report = generate_report(rag_results, sql_results)
    report_md = format_report(report)

    elapsed = time.time() - start
    print(f"\n评测完成，耗时 {elapsed:.1f}s")

    # 输出
    if output_file:
        Path(output_file).write_text(report_md, encoding="utf-8")
        print(f"报告已保存: {output_file}")
    else:
        print("\n" + report_md)

    # CI 模式
    if ci_mode:
        min_pass_rate = 0.6
        if report.pass_rate < min_pass_rate:
            print(f"\n[CI FAIL] 通过率 {report.pass_rate:.1%} 低于阈值 {min_pass_rate:.0%}")
            sys.exit(1)
        else:
            print(f"\n[CI PASS] 通过率 {report.pass_rate:.1%} >= 阈值 {min_pass_rate:.0%}")
            sys.exit(0)

    return report


if __name__ == "__main__":
    ci = "--ci" in sys.argv
    output = None
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output = sys.argv[i + 1]
    main(ci_mode=ci, output_file=output)
