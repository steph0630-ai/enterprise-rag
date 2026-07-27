"""检索逻辑：embed query → 向量检索 → 返回上下文"""

import logging
from app.core.embedding import EmbeddingService
from app.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Retriever:
    """封装检索链路"""

    def __init__(self):
        self.embedder = EmbeddingService()
        self.store = VectorStore()

    def retrieve(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[dict]:
        """
        检索相关文档 chunk：
        1. 用户 query → embedding
        2. Qdrant 向量搜索
        3. 返回命中的 chunks
        """
        query_vec = self.embedder.embed_single(query)
        results = self.store.search(query_vec, top_k=top_k, filters=filters)

        logger.info("Retrieved %s chunks for query '%s...'", len(results), query[:50])
        return results

    def format_context(self, results: list[dict]) -> str:
        """将检索结果格式化为 LLM 上下文"""
        if not results:
            return "（未找到相关文档）"

        parts = []
        for i, r in enumerate(results):
            source = r["title"] or r["source_name"] or "未知来源"
            parts.append(
                f"[文档片段 {i + 1}] 来源: {source}\n{r['content']}"
            )

        return "\n\n---\n\n".join(parts)
