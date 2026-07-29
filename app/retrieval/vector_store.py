"""Qdrant 向量数据库封装 — 支持本地模式（无需 Docker）"""

import logging
import uuid
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import get_settings

logger = logging.getLogger(__name__)


class VectorStore:
    """管理 Qdrant 中知识库的写入和查询"""

    def __init__(self):
        settings = get_settings()
        self.vector_dim = settings.vector_dim
        self.collection = settings.qdrant_collection_name

        # 本地模式：数据存磁盘，无需 Docker
        if settings.qdrant_url.startswith("local:"):
            local_path = settings.qdrant_url.replace("local:", "")
            Path(local_path).mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=local_path)
            logger.info("Qdrant 本地模式: %s", local_path)
        else:
            self.client = QdrantClient(url=settings.qdrant_url)
            logger.info("Qdrant 远程模式: %s", settings.qdrant_url)

        self._ensure_collection()

    def _ensure_collection(self):
        try:
            self.client.get_collection(self.collection)
        except (UnexpectedResponse, ValueError):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=qmodels.VectorParams(
                    size=self.vector_dim,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            logger.info("Collection '%s' 已创建", self.collection)

    def upsert_document(self, doc_id: str, chunks: list, embeddings: list[list[float]], checksum: str = ""):
        # 删旧
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
                )
            ),
        )
        # 写新
        points = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            points.append(qmodels.PointStruct(
                id=point_id, vector=emb,
                payload={
                    "doc_id": doc_id,
                    "chunk_index": chunk.metadata.get("chunk_index", i),
                    "content": chunk.content,
                    "title": chunk.metadata.get("title", ""),
                    "source_type": chunk.metadata.get("source_type", ""),
                    "source_name": chunk.metadata.get("source_name", ""),
                    "file_path": chunk.metadata.get("file_path", ""),
                    "url": chunk.metadata.get("url", ""),
                    "tags": chunk.metadata.get("tags", []),
                    "checksum": checksum,
                },
            ))
        self.client.upsert(collection_name=self.collection, points=points)
        logger.info("Upserted %s points for %s", len(points), doc_id)

    def get_doc_checksum(self, doc_id: str) -> str | None:
        results, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
            ),
            limit=1, with_payload=["checksum"],
        )
        if results:
            return results[0].payload.get("checksum")
        return None

    def search(self, query_vector: list[float], top_k: int = 5, filters: dict | None = None) -> list[dict]:
        must_conditions = []
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    must_conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchAny(any=value)))
                else:
                    must_conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value)))
        q_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=top_k,
            query_filter=q_filter,
            with_payload=True,
        )
        return [
            {
                "id": r.id, "score": r.score,
                "content": r.payload.get("content", ""),
                "doc_id": r.payload.get("doc_id", ""),
                "title": r.payload.get("title", ""),
                "source_name": r.payload.get("source_name", ""),
                "file_path": r.payload.get("file_path", ""),
                "url": r.payload.get("url", ""),
                "chunk_index": r.payload.get("chunk_index", 0),
                "tags": r.payload.get("tags", []),
            }
            for r in response.points
        ]

    def delete_document(self, doc_id: str):
        """从 Qdrant 中删除指定文档的所有 points"""
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
                )
            ),
        )
        logger.info("Deleted all points for doc_id=%s", doc_id)

    def count(self) -> int:
        return self.client.count(self.collection).count
