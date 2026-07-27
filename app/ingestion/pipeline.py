"""数据摄入 Pipeline 编排器：扫描 → 解析 → 分块 → 向量化 → 写入"""

import logging
from dataclasses import dataclass, field

from app.core.parser import DocumentParser
from app.core.chunker import RecursiveCharacterChunker, Chunk
from app.core.embedding import EmbeddingService
from app.retrieval.vector_store import VectorStore
from app.retrieval.hybrid_retriever import get_keyword_index
from app.ingestion.connectors.base import BaseConnector
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    total_documents: int = 0
    total_chunks: int = 0
    new_documents: int = 0
    skipped_documents: int = 0
    failed_documents: int = 0
    errors: list[str] = field(default_factory=list)


class IngestionPipeline:
    """编排整个摄入流程"""

    def __init__(self):
        settings = get_settings()
        self.parser = DocumentParser()
        self.chunker = RecursiveCharacterChunker(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self.embedder = EmbeddingService()
        self.vector_store = VectorStore()

    def run(self, connector: BaseConnector, since: str | None = None) -> IngestionResult:
        """
        执行完整摄入流程：
        1. connector 列出文档
        2. 逐个解析 → 分块
        3. 向量化 → 写入 Qdrant
        """
        result = IngestionResult()

        metas = connector.list_documents(since=since)
        result.total_documents = len(metas)
        logger.info("Starting ingestion: %s documents from %s", len(metas), connector.source_type)

        for meta in metas:
            try:
                # 1. 拉取内容
                doc = connector.fetch_content(meta)

                # 2. 按文档 path checksum 判断是否需要更新向量库
                stored_hash = self.vector_store.get_doc_checksum(doc.meta.doc_id)
                vector_needs_update = (stored_hash != doc.checksum)

                # 3. 解析为纯文本
                text, file_meta = self.parser.parse(meta.file_path or meta.doc_id)
                merged_meta = {
                    **file_meta,
                    "doc_id": meta.doc_id,
                    "title": meta.title,
                    "source_type": meta.source_type,
                    "source_name": meta.source_name,
                    "url": meta.url,
                    "tags": meta.tags,
                    "checksum": doc.checksum,
                }

                # 4. 分块
                chunks: list[Chunk] = self.chunker.chunk_document(text, merged_meta)

                payload = {
                    "title": merged_meta.get("title", ""),
                    "source_name": merged_meta.get("source_name", ""),
                    "source_type": merged_meta.get("source_type", ""),
                    "file_path": merged_meta.get("file_path", ""),
                    "url": merged_meta.get("url", ""),
                    "tags": merged_meta.get("tags", []),
                }

                # 5. BM25 关键词索引（每次都更新，向量不变不影响 BM25）
                keyword_index = get_keyword_index()
                keyword_index.remove_document(meta.doc_id)
                for chunk in chunks:
                    keyword_index.add_document(
                        doc_id=meta.doc_id,
                        chunk_index=chunk.metadata.get("chunk_index", 0),
                        content=chunk.content,
                        payload=payload,
                    )

                # 6. 向量库（只有内容变化才更新，省 embedding 费用）
                if vector_needs_update:
                    chunk_texts = [c.content for c in chunks]
                    embeddings = self.embedder.embed(chunk_texts)
                    self.vector_store.upsert_document(
                        doc_id=meta.doc_id,
                        chunks=chunks,
                        embeddings=embeddings,
                        checksum=doc.checksum,
                    )
                    result.new_documents += 1
                else:
                    result.skipped_documents += 1
                    logger.debug("Vector skipped (unchanged): %s", meta.doc_id)

                result.total_chunks += len(chunks)
                logger.info("Ingested: %s → %s chunks (vector=%s)", meta.doc_id, len(chunks), "updated" if vector_needs_update else "skipped")

            except Exception as e:
                result.failed_documents += 1
                error_msg = f"{meta.doc_id}: {e}"
                result.errors.append(error_msg)
                logger.error("Failed to ingest %s: %s", meta.doc_id, e, exc_info=True)

        logger.info(
            "Ingestion complete: %s new, %s skipped, %s failed, %s chunks",
            result.new_documents, result.skipped_documents, result.failed_documents, result.total_chunks,
        )
        return result
