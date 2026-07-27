"""文档摄入 API"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.connectors.local_fs import LocalFSConnector
from app.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    source_type: str = "local_fs"
    path: str = "./docs/samples"


@router.post("/run")
def run_ingestion(req: IngestRequest):
    """触发文档摄入"""
    store = VectorStore()
    old_count = store.count()

    try:
        pipeline = IngestionPipeline()

        if req.source_type == "local_fs":
            connector = LocalFSConnector(root_path=req.path)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的数据源类型: {req.source_type}")

        result = pipeline.run(connector)
        new_count = store.count()

        return {
            "status": "ok",
            "old_vector_count": old_count,
            "new_vector_count": new_count,
            "total_documents": result.total_documents,
            "new_documents": result.new_documents,
            "skipped_documents": result.skipped_documents,
            "failed_documents": result.failed_documents,
            "total_chunks": result.total_chunks,
            "errors": result.errors[:10],  # 最多返回前 10 条错误
        }

    except Exception as e:
        logger.error("Ingestion failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
def get_stats():
    """查看知识库统计"""
    store = VectorStore()
    from app.retrieval.hybrid_retriever import get_keyword_index
    kw_idx = get_keyword_index()
    return {
        "total_vectors": store.count(),
        "collection": store.collection,
        "bm25_documents": kw_idx.document_count,
        "bm25_vocabulary": kw_idx.vocabulary_size,
    }
