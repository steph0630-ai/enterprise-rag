"""混合检索引擎：向量检索 + BM25 关键词检索 + RRF 融合"""

import logging
from app.core.embedding import EmbeddingService
from app.retrieval.vector_store import VectorStore
from app.retrieval.keyword_search import BM25KeywordSearch, KeywordResult

logger = logging.getLogger(__name__)


# ==================== 全局单例（跨请求共享 BM25 索引） ====================

_keyword_index: BM25KeywordSearch | None = None


def get_keyword_index() -> BM25KeywordSearch:
    global _keyword_index
    if _keyword_index is None:
        _keyword_index = BM25KeywordSearch()
        logger.info("BM25 index initialized (empty)")
    return _keyword_index


def reset_keyword_index():
    global _keyword_index
    _keyword_index = BM25KeywordSearch()
    logger.info("BM25 index reset")


# ==================== RRF 融合 ====================

def reciprocal_rank_fusion(
    vector_results: list[dict],
    keyword_results: list[KeywordResult],
    k: int = 60,
    top_k: int = 5,
) -> list[dict]:
    """
    RRF (Reciprocal Rank Fusion) 融合两路检索结果。

    公式: RRF(d) = Σ 1 / (k + rank_i(d))
    - k=60 是常用默认值，避免单个极端排名主导
    - 如果某文档只在其中一路出现，另一路贡献 0
    """
    scores: dict[str, float] = {}     # composite_key → RRF score
    doc_map: dict[str, dict] = {}      # composite_key → merged metadata

    # 向量检索结果
    for rank, item in enumerate(vector_results):
        key = f"{item['doc_id']}::{item['chunk_index']}"
        rrf = 1.0 / (k + rank + 1)
        scores[key] = scores.get(key, 0.0) + rrf
        doc_map[key] = {
            "doc_id": item["doc_id"],
            "chunk_index": item["chunk_index"],
            "content": item["content"],
            "title": item["title"],
            "source_name": item["source_name"],
            "file_path": item["file_path"],
            "url": item["url"],
            "tags": item["tags"],
            "vector_score": item["score"],
            "vector_rank": rank + 1,
            "keyword_score": 0.0,
            "keyword_rank": None,
        }

    # 关键词检索结果
    for rank, item in enumerate(keyword_results):
        key = f"{item.doc_id}::{item.chunk_index}"
        rrf = 1.0 / (k + rank + 1)
        scores[key] = scores.get(key, 0.0) + rrf

        if key in doc_map:
            doc_map[key]["keyword_score"] = item.score
            doc_map[key]["keyword_rank"] = rank + 1
        else:
            doc_map[key] = {
                "doc_id": item.doc_id,
                "chunk_index": item.chunk_index,
                "content": item.content,
                "title": item.title,
                "source_name": item.source_name,
                "file_path": item.file_path,
                "url": item.url,
                "tags": item.tags,
                "vector_score": 0.0,
                "vector_rank": None,
                "keyword_score": item.score,
                "keyword_rank": rank + 1,
            }

    # 按 RRF 分数降序排列，取 top-K
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = ranked[:top_k]

    results = []
    for key, rrf_score in top:
        item = doc_map[key]
        item["rrf_score"] = round(rrf_score, 6)
        item["score"] = item["rrf_score"]  # 统一 score 字段
        results.append(item)

    return results


# ==================== 混合检索器 ====================

class HybridRetriever:
    """混合检索器：向量 + BM25 → RRF 融合"""

    def __init__(self, vector_weight: float = 0.5):
        self.embedder = EmbeddingService()
        self.vector_store = VectorStore()
        self.keyword_index = get_keyword_index()
        self.expand_n = 20  # 每路先取 top-N

    def retrieve(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[dict]:
        """混合检索主入口"""
        # 1. 向量检索
        query_vec = self.embedder.embed_single(query)
        vector_results = self.vector_store.search(query_vec, top_k=self.expand_n, filters=filters)

        # 2. 关键词检索
        keyword_results = self.keyword_index.search(query, top_k=self.expand_n)

        # 3. RRF 融合
        fused = reciprocal_rank_fusion(
            vector_results=vector_results,
            keyword_results=keyword_results,
            k=60,
            top_k=top_k,
        )

        logger.info(
            "Hybrid: vector=%s, keyword=%s → fused=%s (query='%s...')",
            len(vector_results), len(keyword_results), len(fused), query[:50],
        )

        # 记录融合统计
        both = sum(1 for r in fused if r.get("vector_rank") and r.get("keyword_rank"))
        v_only = sum(1 for r in fused if r.get("vector_rank") and not r.get("keyword_rank"))
        k_only = sum(1 for r in fused if r.get("keyword_rank") and not r.get("vector_rank"))
        logger.debug("RRF breakdown: both=%s, vector_only=%s, keyword_only=%s", both, v_only, k_only)

        return fused

    def format_context(self, results: list[dict]) -> str:
        """将检索结果格式化为 LLM 上下文"""
        if not results:
            return "（未找到相关文档）"

        parts = []
        for i, r in enumerate(results):
            source = r.get("title") or r.get("source_name") or "未知来源"
            parts.append(f"[文档片段 {i + 1}] 来源: {source}\n{r['content']}")

        return "\n\n---\n\n".join(parts)

    # ==================== 索引管理 ====================

    def index_chunks(self, doc_id: str, chunks: list, payload: dict):
        """将文档 chunks 加入 BM25 索引"""
        for chunk in chunks:
            self.keyword_index.add_document(
                doc_id=doc_id,
                chunk_index=chunk.metadata.get("chunk_index", 0),
                content=chunk.content,
                payload=payload,
            )

    def remove_from_index(self, doc_id: str):
        """从 BM25 索引中移除文档"""
        self.keyword_index.remove_document(doc_id)

    @property
    def index_stats(self) -> dict:
        return {
            "bm25_documents": self.keyword_index.document_count,
            "bm25_vocabulary": self.keyword_index.vocabulary_size,
        }
