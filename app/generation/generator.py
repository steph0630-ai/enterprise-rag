"""答案生成器：检索 → 精排 → LLM 生成 → 引用解析"""

import re
import logging
from dataclasses import dataclass, field

from app.core.llm import LLMClient
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.reranker import LLMReranker
from app.generation.prompts import RAG_SYSTEM_PROMPT, RAG_USER_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """引用"""
    index: int
    title: str
    source_name: str
    content_excerpt: str


@dataclass
class RAGAnswer:
    """RAG 回答"""
    answer: str
    citations: list[Citation] = field(default_factory=list)
    context_used: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    query_rewritten: str | None = None


class Generator:
    """编排 RAG 问答完整链路"""

    def __init__(self, enable_rerank: bool = True):
        self.llm = LLMClient()
        self.retriever = HybridRetriever()
        self.reranker = LLMReranker() if enable_rerank else None
        self.rerank_candidates = 10  # 粗筛取 top-10 送给 Reranker

    def answer(self, query: str, top_k: int = 5) -> RAGAnswer:
        """单轮问答（无查询改写）"""
        return self._answer_internal(query, top_k)

    def answer_with_rewrite(self, query: str, rewritten_query: str, top_k: int = 5) -> RAGAnswer:
        """使用改写后的 query 检索，但最终回答时用原始 query"""
        result = self._answer_internal(rewritten_query, top_k)
        result.query_rewritten = rewritten_query
        return result

    def _answer_internal(self, query: str, top_k: int = 5) -> RAGAnswer:
        """内部实现：检索 → 精排 → 生成"""

        # 1. 混合检索（粗筛），取更多候选给 Reranker
        retrieve_k = self.rerank_candidates if self.reranker else top_k
        results = self.retriever.retrieve(query, top_k=retrieve_k)

        # 2. Reranker 精排
        if self.reranker and len(results) > top_k:
            results = self.reranker.rerank(query, results, top_k=top_k)

        # 3. 组装上下文
        context = self.retriever.format_context(results)

        # 4. Prompt + LLM 生成
        messages = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": RAG_USER_PROMPT.format(context=context, query=query)},
        ]

        raw_answer = self.llm.chat(messages)

        # 5. 解析引用
        citations = self._parse_citations(raw_answer, results)

        return RAGAnswer(
            answer=raw_answer,
            citations=citations,
            context_used=results,
        )

    def answer_stream(self, query: str, top_k: int = 5):
        """流式问答"""
        retrieve_k = self.rerank_candidates if self.reranker else top_k
        results = self.retriever.retrieve(query, top_k=retrieve_k)

        if self.reranker and len(results) > top_k:
            results = self.reranker.rerank(query, results, top_k=top_k)

        context = self.retriever.format_context(results)

        messages = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": RAG_USER_PROMPT.format(context=context, query=query)},
        ]

        yield from self.llm.chat_stream(messages)

    # ==================== 引用解析 ====================

    def _parse_citations(self, answer: str, context: list[dict]) -> list[Citation]:
        refs = set(re.findall(r"\[(\d+)\]", answer))
        citations = []
        for ref in refs:
            idx = int(ref) - 1
            if 0 <= idx < len(context):
                ctx = context[idx]
                citations.append(Citation(
                    index=idx + 1,
                    title=ctx.get("title", "未知文档"),
                    source_name=ctx.get("source_name", ""),
                    content_excerpt=ctx["content"][:150] + "...",
                ))

        return sorted(citations, key=lambda c: c.index)
