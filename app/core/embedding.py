"""Embedding 服务 — 通过 OpenAI 兼容接口调用 bge-m3"""

import logging
from openai import OpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """文本向量化，支持批量"""

    def __init__(self):
        settings = get_settings()
        self.client = OpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
        self.model = settings.embedding_model
        self.dim = settings.vector_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本 → 向量列表"""
        if not texts:
            return []

        # bge-m3 的最大 batch size 通常是 32，这里保守一点用 16
        batch_size = 16
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            logger.debug("Embedding batch %s/%s, size=%s", i // batch_size + 1, (len(texts) - 1) // batch_size + 1, len(batch))
            response = self.client.embeddings.create(model=self.model, input=batch)
            all_embeddings.extend([item.embedding for item in response.data])

        return all_embeddings

    def embed_single(self, text: str) -> list[float]:
        """单条文本 → 向量"""
        return self.embed([text])[0]
