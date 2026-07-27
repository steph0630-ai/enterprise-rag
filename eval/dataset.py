"""评测数据集管理 — 加载、标注、管理测试问答对"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalQuery:
    """单条评测样本"""
    id: str
    query: str
    intent: str  # "rag" | "sql"
    # RAG 评测字段
    expected_chunks: list[str] = field(default_factory=list)  # 必须命中的文档片段关键词
    must_contain: list[str] = field(default_factory=list)     # 答案必须包含的关键词
    must_not_contain: list[str] = field(default_factory=list)  # 答案不能包含的内容
    # NL2SQL 评测字段
    expected_sql_keywords: list[str] = field(default_factory=list)  # SQL 必须包含的关键词 (SUM, GROUP BY, etc.)
    expected_answer_contains: list[str] = field(default_factory=list)  # 答案包含的数字/事实
    # 元数据
    difficulty: str = "easy"  # easy | medium | hard
    tags: list[str] = field(default_factory=list)


# ── 标注数据集 ──

EVAL_DATASET: list[EvalQuery] = [
    # ===== RAG 评测样本 =====
    EvalQuery(
        id="rag-001",
        query="订单服务超时时间是多少",
        intent="rag",
        expected_chunks=["超时", "30"],
        must_contain=["30", "秒"],
        must_not_contain=["无法找到"],
        difficulty="easy",
        tags=["订单服务", "精确匹配"],
    ),
    EvalQuery(
        id="rag-002",
        query="订单服务监听哪个端口",
        intent="rag",
        expected_chunks=["端口", "8080"],
        must_contain=["8080"],
        must_not_contain=["无法找到"],
        difficulty="easy",
        tags=["订单服务", "精确匹配"],
    ),
    EvalQuery(
        id="rag-003",
        query="Redis 怎么配置最大内存",
        intent="rag",
        expected_chunks=["内存", "配置", "maxmemory"],
        must_contain=["maxmemory", "最大"],
        must_not_contain=["无法找到"],
        difficulty="medium",
        tags=["Redis", "配置"],
    ),
    EvalQuery(
        id="rag-004",
        query="订单服务部署需要哪些步骤",
        intent="rag",
        expected_chunks=["部署", "步骤"],
        must_contain=["部署", "配置"],
        must_not_contain=["无法找到"],
        difficulty="medium",
        tags=["订单服务", "流程"],
    ),
    EvalQuery(
        id="rag-005",
        query="API 接口返回什么状态码表示成功",
        intent="rag",
        expected_chunks=["状态码", "200", "成功"],
        must_contain=["200"],
        must_not_contain=["无法找到"],
        difficulty="easy",
        tags=["API", "精确匹配"],
    ),
    EvalQuery(
        id="rag-006",
        query="Redis 持久化有哪两种策略",
        intent="rag",
        expected_chunks=["持久化", "RDB", "AOF"],
        must_contain=["RDB", "AOF"],
        must_not_contain=["无法找到"],
        difficulty="medium",
        tags=["Redis", "概念"],
    ),
    EvalQuery(
        id="rag-007",
        query="订单创建超时怎么排查",
        intent="rag",
        expected_chunks=["超时", "排查", "日志"],
        must_contain=["日志", "排查"],
        must_not_contain=["无法找到"],
        difficulty="medium",
        tags=["订单服务", "排查"],
    ),
    # ===== NL2SQL 评测样本（Brazilian E-Commerce）=====
    EvalQuery(
        id="sql-001",
        query="总共有多少订单",
        intent="sql",
        expected_sql_keywords=["SELECT", "COUNT", "FROM", "orders"],
        expected_answer_contains=["99441"],
        difficulty="easy",
        tags=["聚合", "计数"],
    ),
    EvalQuery(
        id="sql-002",
        query="订单数量最多的州是哪个",
        intent="sql",
        expected_sql_keywords=["SELECT", "customer_state", "COUNT", "ORDER BY", "DESC", "LIMIT"],
        expected_answer_contains=["SP"],
        difficulty="easy",
        tags=["JOIN", "GROUP BY", "排序"],
    ),
    EvalQuery(
        id="sql-003",
        query="每月订单量是多少",
        intent="sql",
        expected_sql_keywords=["strftime", "COUNT", "GROUP BY", "month"],
        expected_answer_contains=["2017"],
        difficulty="medium",
        tags=["聚合", "时间", "GROUP BY"],
    ),
    EvalQuery(
        id="sql-004",
        query="信用卡支付占总支付的比例是多少",
        intent="sql",
        expected_sql_keywords=["credit_card", "COUNT", "SUM", "payment_type"],
        expected_answer_contains=["73"],
        difficulty="easy",
        tags=["聚合", "百分比"],
    ),
    EvalQuery(
        id="sql-005",
        query="每个州的客户数量",
        intent="sql",
        expected_sql_keywords=["customer_state", "COUNT", "GROUP BY"],
        expected_answer_contains=["SP"],
        difficulty="easy",
        tags=["聚合", "计数", "GROUP BY"],
    ),
    EvalQuery(
        id="sql-006",
        query="平均评分最高的 5 个商品类目",
        intent="sql",
        expected_sql_keywords=["AVG", "review_score", "ORDER BY", "DESC", "LIMIT"],
        expected_answer_contains=["5"],
        difficulty="medium",
        tags=["JOIN", "排序", "评分"],
    ),
    EvalQuery(
        id="sql-007",
        query="有多少不同的支付方式",
        intent="sql",
        expected_sql_keywords=["DISTINCT", "payment_type", "COUNT"],
        expected_answer_contains=["4"],
        difficulty="easy",
        tags=["去重", "计数"],
    ),
]


def load_dataset() -> list[EvalQuery]:
    """加载评测数据集"""
    return EVAL_DATASET


def load_dataset_by_intent(intent: str) -> list[EvalQuery]:
    """按意图筛选评测样本"""
    return [q for q in EVAL_DATASET if q.intent == intent]


def get_dataset_stats() -> dict:
    """数据集统计"""
    queries = EVAL_DATASET
    return {
        "total": len(queries),
        "by_intent": {
            "rag": len([q for q in queries if q.intent == "rag"]),
            "sql": len([q for q in queries if q.intent == "sql"]),
        },
        "by_difficulty": {
            "easy": len([q for q in queries if q.difficulty == "easy"]),
            "medium": len([q for q in queries if q.difficulty == "medium"]),
            "hard": len([q for q in queries if q.difficulty == "hard"]),
        },
        "tags": list(set(tag for q in queries for tag in q.tags)),
    }
