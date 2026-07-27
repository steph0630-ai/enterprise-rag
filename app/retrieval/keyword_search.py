"""BM25 / TF-IDF 关键词检索引擎 — 纯 Python 实现，零外部依赖"""

import re
import math
import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class KeywordResult:
    doc_id: str
    chunk_index: int
    content: str
    score: float
    title: str = ""
    source_name: str = ""
    file_path: str = ""
    url: str = ""
    tags: list = field(default_factory=list)


class BM25KeywordSearch:
    """
    轻量级 BM25 关键词检索引擎：
    - 索引阶段：对所有 chunk 构建倒排索引
    - 检索阶段：BM25 打分，返回 top-K
    - 支持增删文档
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1          # BM25 词频饱和参数
        self.b = b             # 文档长度归一化参数

        # 索引数据
        self.documents: list[dict] = []                # 所有文档的 payload
        self.doc_lengths: list[int] = []               # 每个文档的 token 数
        self.avg_doc_len: float = 0.0                  # 平均文档长度
        self.inverted_index: dict[str, dict[int, int]] = defaultdict(dict)  # term → {doc_idx: tf}
        self.idf: dict[str, float] = {}                # term → idf
        self.total_docs: int = 0

        # doc_id → [doc_indices] 映射（用于删除）
        self._doc_id_to_indices: dict[str, list[int]] = defaultdict(list)

    # ==================== 分词 ====================

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """中文 + 英文混合分词"""
        # 中文：按字切分后合并 CJK 连续字符为 bigram
        # 英文：小写 + 拆分
        text = text.lower()
        # 提取中英文字符序列
        tokens = re.findall(r"[一-鿿]+|[a-z0-9]+", text)

        result = []
        for token in tokens:
            if re.match(r"[一-鿿]", token[0]):
                # 中文：单字 + bigram
                result.extend(token)  # 单字
                result.extend(token[i : i + 2] for i in range(len(token) - 1))  # bigram
            else:
                result.append(token)

        return [t for t in result if len(t) >= 1]

    # ==================== 索引 ====================

    def add_document(self, doc_id: str, chunk_index: int, content: str, payload: dict):
        """添加单个文档 chunk 到索引"""
        tokens = self.tokenize(content)
        doc_idx = len(self.documents)

        self.documents.append({
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "content": content,
            "title": payload.get("title", ""),
            "source_name": payload.get("source_name", ""),
            "file_path": payload.get("file_path", ""),
            "url": payload.get("url", ""),
            "tags": payload.get("tags", []),
        })
        self.doc_lengths.append(len(tokens))
        self._doc_id_to_indices[doc_id].append(doc_idx)
        self.total_docs += 1

        # 更新倒排索引
        term_freq = defaultdict(int)
        for t in tokens:
            term_freq[t] += 1

        for term, tf in term_freq.items():
            self.inverted_index[term][doc_idx] = tf

        # 更新平均长度
        self.avg_doc_len = sum(self.doc_lengths) / max(self.total_docs, 1)

    def remove_document(self, doc_id: str):
        """删除文档的所有 chunks"""
        indices = self._doc_id_to_indices.pop(doc_id, [])
        # 从倒排索引中移除
        for doc_idx in indices:
            for term, postings in self.inverted_index.items():
                postings.pop(doc_idx, None)
        # 清理空词条
        empty_terms = [t for t, p in self.inverted_index.items() if not p]
        for t in empty_terms:
            del self.inverted_index[t]
            self.idf.pop(t, None)

        if indices:
            logger.info("Removed %s chunks for doc_id=%s from BM25 index", len(indices), doc_id)

    # ==================== 计算 IDF ====================

    def _compute_idf(self, term: str) -> float:
        """计算某个 term 的 IDF"""
        if term in self.idf:
            return self.idf[term]

        doc_freq = len(self.inverted_index.get(term, {}))
        if doc_freq == 0:
            return 0.0

        idf = math.log((self.total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
        self.idf[term] = idf
        return idf

    # ==================== BM25 得分 ====================

    def _bm25_score(self, query_tokens: list[str], doc_idx: int) -> float:
        """计算一个文档对查询的 BM25 得分"""
        score = 0.0
        doc_len = self.doc_lengths[doc_idx]
        norm = 1.0 - self.b + self.b * (doc_len / max(self.avg_doc_len, 1))

        for token in query_tokens:
            idf = self._compute_idf(token)
            if idf == 0:
                continue

            tf = self.inverted_index.get(token, {}).get(doc_idx, 0)
            if tf == 0:
                continue

            numerator = tf * (self.k1 + 1.0)
            denominator = tf + self.k1 * norm
            score += idf * numerator / denominator

        return score

    # ==================== 检索 ====================

    def search(self, query: str, top_k: int = 20) -> list[KeywordResult]:
        """BM25 检索，返回 top-K 结果"""
        if self.total_docs == 0:
            return []

        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []

        # 对每个文档打分
        scores = []
        for doc_idx in range(self.total_docs):
            score = self._bm25_score(query_tokens, doc_idx)
            if score > 0:
                scores.append((doc_idx, score))

        # 排序取 top-K
        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:top_k]

        results = []
        for doc_idx, score in top:
            doc = self.documents[doc_idx]
            results.append(KeywordResult(
                doc_id=doc["doc_id"],
                chunk_index=doc["chunk_index"],
                content=doc["content"],
                score=score,
                title=doc["title"],
                source_name=doc["source_name"],
                file_path=doc["file_path"],
                url=doc["url"],
                tags=doc["tags"],
            ))

        logger.debug("BM25 search: '%s...' → %s results", query[:50], len(results))
        return results

    # ==================== 维护 ====================

    @property
    def document_count(self) -> int:
        return self.total_docs

    @property
    def vocabulary_size(self) -> int:
        return len(self.inverted_index)
