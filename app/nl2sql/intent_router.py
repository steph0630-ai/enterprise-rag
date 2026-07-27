"""意图路由器 — 判断用户问题应该走 RAG 还是 NL2SQL"""

import json
import logging

from app.core.llm import LLMClient
from app.nl2sql.schema_manager import SchemaManager

logger = logging.getLogger(__name__)

INTENT_ROUTER_PROMPT = """你是一个查询意图分类器。判断用户的问题应该用哪种方式回答：

- **rag**: 问题涉及文档内容、操作手册、流程说明、配置参数、概念解释等**非结构化文本**
- **sql**: 问题涉及数据统计、汇总排名、数值对比、计数求和等**结构化数据查询**

## 判断规则

| 问题类型 | 示例 | 路由到 |
|---------|------|--------|
| "XXX怎么部署/配置/排查" | 操作手册类 | rag |
| "XXX是什么/为什么/原理" | 概念解释类 | rag |
| "退货政策是什么" | 规则说明类 | rag |
| "总销售额/总订单量是多少" | 汇总聚合类 | sql |
| "哪个商品销量最高" | 排名排序类 | sql |
| "A和B对比销售额" | 数值对比类 | sql |
| "圣保罗有多少客户" | 计数类 | sql |
| "评分最低的商品类目是什么" | 需要计算 | sql |

## 可用数据库表

{schema_summary}

## 用户问题

{query}

## 输出格式（严格 JSON，不要输出其他内容）

{{"intent": "rag" | "sql", "confidence": 0.0-1.0, "reason": "简短理由"}}"""


class IntentRouter:
    """查询意图路由器"""

    def __init__(self, schema_manager: SchemaManager | None = None):
        self.schema_manager = schema_manager
        self.llm = LLMClient()

    def route(self, query: str) -> dict:
        """
        判断用户查询的意图。

        Returns:
            {"intent": "rag" | "sql", "confidence": float, "reason": str}
        """
        # 构建 schema 摘要
        schema_summary = "无可用数据库"
        if self.schema_manager:
            try:
                tables = self.schema_manager.get_tables()
                schema_summary = f"共 {len(tables)} 张表: " + ", ".join(tables)
            except Exception:
                pass

        prompt = INTENT_ROUTER_PROMPT.format(
            schema_summary=schema_summary,
            query=query,
        )

        try:
            raw = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            # 清理可能的 markdown 代码块包装
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            return {
                "intent": result.get("intent", "rag"),
                "confidence": result.get("confidence", 0.5),
                "reason": result.get("reason", ""),
            }
        except Exception as e:
            logger.warning("Intent routing failed, defaulting to rag: %s", e)
            return {"intent": "rag", "confidence": 0.0, "reason": f"路由失败回退: {e}"}
