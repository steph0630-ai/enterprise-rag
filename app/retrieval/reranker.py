"""Reranker 精排模块：对粗筛结果做二次排序

支持两种模式：
1. LLM-as-Reranker（默认）: 用 DeepSeek 对候选文档打分，零额外依赖
2. API-based: 接外部 Reranker API（如 SiliconFlow / Cohere）
"""

import json
import logging

from app.core.llm import LLMClient

logger = logging.getLogger(__name__)


RERANK_PROMPT = """你是一个文档相关性评估器。给定用户问题，评估以下文档片段的相关性并排序。

## 用户问题
{query}

## 候选文档片段
{candidates}

## 任务
对每个文档片段打分（0-100），分数越高表示越能回答问题。
只返回 JSON 数组，不要任何其他内容。格式：
[{{"id": 文档编号, "score": 得分, "reason": "一句话理由"}}]

按 score 降序排列："""


class LLMReranker:
    """用 LLM 做精排：给候选文档打分，取 top-K"""

    def __init__(self):
        self.llm = LLMClient()

    def rerank(self, query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
        """
        对候选文档精排

        Args:
            query: 用户问题
            candidates: RRF 融合后的候选文档列表
            top_k: 返回前 K 个

        Returns:
            按相关性重新排序后的 top-K 文档
        """
        n = len(candidates)
        if n <= top_k:
            # 候选数不超过 top_k，不需要重排
            return candidates

        # 组装候选文本
        candidate_texts = []
        for i, c in enumerate(candidates):
            snippet = c["content"][:300].replace("\n", " ")
            candidate_texts.append(f"[文档 {i + 1}] (来源: {c.get('title', '未知')}) {snippet}")

        candidates_str = "\n\n".join(candidate_texts)

        try:
            raw = self.llm.chat(
                messages=[{"role": "user", "content": RERANK_PROMPT.format(query=query, candidates=candidates_str)}],
                temperature=0.1,
                max_tokens=1024,
            )

            # 解析 LLM 返回的 JSON
            scores = self._parse_scores(raw, n)

            # 按得分降序排列，取 top-K
            ranked_indices = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
            top_indices = ranked_indices[:top_k]

            reranked = []
            for idx in top_indices:
                item = dict(candidates[idx])
                item["rerank_score"] = scores[idx]
                item["score"] = scores[idx] / 100.0  # 归一化到 0-1
                reranked.append(item)

            logger.info(
                "Reranker: %s candidates → top-%s (scores: %s)",
                n, top_k, [f"{scores[i]}" for i in top_indices],
            )
            return reranked

        except Exception as e:
            logger.warning("Reranker failed, falling back to RRF order: %s", e)
            # 失败时降级：直接返回 RRF 的 top-K
            return candidates[:top_k]

    def _parse_scores(self, raw: str, expected_count: int) -> dict[int, int]:
        """解析 LLM 返回的 JSON 评分"""
        # 清理可能的前后缀
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]

        try:
            items = json.loads(raw)
            scores = {}
            for item in items:
                idx = int(item["id"]) - 1  # 文档编号转 0-based index
                if 0 <= idx < expected_count:
                    scores[idx] = int(item["score"])
            return scores
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse reranker output: %s\nRaw: %s", e, raw[:200])
            raise
