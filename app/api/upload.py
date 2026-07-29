"""文件上传 API — 用户自建知识库：上传文档(RAG) + 上传数据库(NL2SQL)"""

import logging
import shutil
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.config import PROJECT_ROOT
from app.ingestion.pipeline import IngestionPipeline
from app.retrieval.vector_store import VectorStore
from app.retrieval.hybrid_retriever import get_keyword_index
from app.nl2sql.db_manager import get_db_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/upload", tags=["upload"])

# 上传目录
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"
DATABASES_DIR = PROJECT_ROOT / "data" / "databases"

# 支持的文件类型
ALLOWED_DOC_SUFFIXES = {
    ".md", ".txt", ".markdown",
    ".py", ".js", ".ts", ".html", ".htm",
    ".json", ".yaml", ".yml",
    ".java", ".go", ".rs", ".sql",
    ".cfg", ".ini", ".conf", ".toml", ".xml",
    ".csv", ".log",
}

MAX_DOC_SIZE = 20 * 1024 * 1024   # 20MB
MAX_DB_SIZE = 200 * 1024 * 1024   # 200MB


# ── Models ──

class UploadDocResponse(BaseModel):
    status: str
    filename: str
    doc_id: str
    chunks: int
    message: str


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    source_type: str
    chunks: int


class DatabaseInfo(BaseModel):
    filename: str
    size_bytes: int
    tables: list[str]
    is_active: bool


class SwitchDBRequest(BaseModel):
    filename: str


# ── Document Upload ──

@router.post("/document", response_model=UploadDocResponse)
async def upload_document(file: UploadFile = File(...)):
    """上传单个文档，自动解析、分块、向量化并加入知识库"""
    # 1. 校验文件名
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_DOC_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {suffix}。支持: {', '.join(sorted(ALLOWED_DOC_SUFFIXES))}",
        )

    # 2. 读取文件内容
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    if len(content) > MAX_DOC_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大 ({len(content) / 1024 / 1024:.1f}MB)，最大 {MAX_DOC_SIZE / 1024 / 1024:.0f}MB",
        )

    # 3. 保存文件
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(file.filename)
    dest_path = UPLOADS_DIR / safe_name

    # 尝试 UTF-8 解码以验证文本文件
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content.decode("latin-1")
        except Exception:
            raise HTTPException(status_code=400, detail="无法识别的文件编码，请上传 UTF-8 文本文件")

    dest_path.write_bytes(content)
    logger.info("File saved: %s (%d bytes)", safe_name, len(content))

    # 4. 运行摄入流水线
    try:
        pipeline = IngestionPipeline()
        doc_id = safe_name
        result = pipeline.run_file(str(dest_path), doc_id=doc_id)
    except Exception as e:
        # 清理失败的文件
        if dest_path.exists():
            dest_path.unlink()
        logger.error("Ingestion failed for %s: %s", safe_name, e)
        raise HTTPException(status_code=500, detail=f"文档处理失败: {e}")

    if result.failed_documents > 0:
        if dest_path.exists():
            dest_path.unlink()
        raise HTTPException(status_code=500, detail=f"文档处理失败: {result.errors[0] if result.errors else '未知错误'}")

    return UploadDocResponse(
        status="ok",
        filename=safe_name,
        doc_id=doc_id,
        chunks=result.total_chunks,
        message=f"成功摄入 {result.total_chunks} 个文本块",
    )


@router.get("/documents", response_model=list[DocumentInfo])
def list_documents():
    """列出所有用户上传的文档"""
    store = VectorStore()
    keyword_index = get_keyword_index()

    # 从 BM25 索引中提取上传文档信息（按 doc_id 聚合）
    uploaded: dict[str, dict] = {}
    for doc in keyword_index.documents:
        if doc.get("source_type") == "upload" or "/uploads/" in doc.get("file_path", ""):
            did = doc["doc_id"]
            if did not in uploaded:
                uploaded[did] = {"doc_id": did, "chunks": 0, "source_type": "upload"}
            uploaded[did]["chunks"] += 1

    # 补全文件系统中的文件（尚未写入 BM25 的情况）
    if UPLOADS_DIR.exists():
        for f in UPLOADS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ALLOWED_DOC_SUFFIXES:
                if f.name not in uploaded:
                    uploaded[f.name] = {"doc_id": f.name, "chunks": 0, "source_type": "upload"}

    return [
        DocumentInfo(
            doc_id=info["doc_id"],
            filename=info["doc_id"],
            source_type=info.get("source_type", "upload"),
            chunks=info["chunks"],
        )
        for info in uploaded.values()
    ]


@router.delete("/document")
def delete_document(filename: str):
    """从知识库中删除指定文档（Qdrant + BM25 + 文件系统）"""
    store = VectorStore()
    keyword_index = get_keyword_index()

    # 删除向量
    store.delete_document(filename)
    # 删除 BM25 索引
    keyword_index.remove_document(filename)
    # 删除文件
    file_path = UPLOADS_DIR / _safe_filename(filename)
    if file_path.exists():
        file_path.unlink()

    logger.info("Document deleted: %s", filename)
    return {"status": "ok", "deleted": filename}


# ── Database Upload ──

@router.post("/database", response_model=dict)
async def upload_database(file: UploadFile = File(...)):
    """上传 SQLite 数据库文件，用于 NL2SQL 查询"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".db", ".sqlite", ".sqlite3", ".db3"}:
        raise HTTPException(status_code=400, detail=f"不支持的数据库文件类型: {suffix}，请上传 .db 或 .sqlite 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    if len(content) > MAX_DB_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"数据库文件过大 ({len(content) / 1024 / 1024:.1f}MB)，最大 {MAX_DB_SIZE / 1024 / 1024:.0f}MB",
        )

    # 校验是否为有效 SQLite 数据库
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
            tmp.write(content)
            tmp.flush()
            conn = sqlite3.connect(tmp.name)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            conn.close()
            table_names = [t[0] for t in tables]
            table_count = len(table_names)
    except sqlite3.Error as e:
        raise HTTPException(status_code=400, detail=f"无效的 SQLite 数据库文件: {e}")

    # 保存
    DATABASES_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(file.filename)
    dest_path = DATABASES_DIR / safe_name
    dest_path.write_bytes(content)

    # 注册到管理器
    db_manager = get_db_manager()
    db_manager.add_database(safe_name, str(dest_path))

    logger.info("Database uploaded: %s (%d bytes, %d tables)", safe_name, len(content), table_count)

    return {
        "status": "ok",
        "filename": safe_name,
        "size_bytes": len(content),
        "tables": table_names,
        "table_count": table_count,
        "message": f"数据库已上传，包含 {table_count} 张表",
    }


@router.get("/databases", response_model=list[DatabaseInfo])
def list_databases():
    """列出所有已上传的数据库"""
    db_manager = get_db_manager()
    dbs = db_manager.list_databases()
    active = db_manager.active_db

    result = []
    for db in dbs:
        result.append(DatabaseInfo(
            filename=db["filename"],
            size_bytes=db["size_bytes"],
            tables=db["tables"],
            is_active=(db["filename"] == active),
        ))
    return result


@router.delete("/database")
def delete_database(filename: str):
    """删除上传的数据库文件"""
    safe_name = _safe_filename(filename)
    db_manager = get_db_manager()
    db_manager.remove_database(safe_name)

    file_path = DATABASES_DIR / safe_name
    if file_path.exists():
        file_path.unlink()

    logger.info("Database deleted: %s", safe_name)
    return {"status": "ok", "deleted": safe_name}


@router.post("/database/switch", response_model=dict)
def switch_database(req: SwitchDBRequest):
    """切换当前使用的 NL2SQL 数据库"""
    safe_name = _safe_filename(req.filename)
    db_manager = get_db_manager()

    if not (DATABASES_DIR / safe_name).exists():
        raise HTTPException(status_code=404, detail=f"数据库文件不存在: {safe_name}")

    db_manager.switch_database(safe_name)
    logger.info("Switched active NL2SQL database to: %s", safe_name)

    return {
        "status": "ok",
        "active_database": safe_name,
        "message": f"已切换到数据库: {safe_name}",
    }


@router.get("/database/active")
def get_active_database():
    """获取当前活跃的数据库信息"""
    db_manager = get_db_manager()
    active = db_manager.active_db

    if not active:
        return {"active_database": None, "message": "未设置活跃数据库"}

    info = db_manager.get_database_info(active)
    return {
        "active_database": active,
        "tables": info.get("tables", []),
        "size_bytes": info.get("size_bytes", 0),
    }


# ── Helpers ──

def _safe_filename(filename: str) -> str:
    """过滤文件名中的危险字符，防止路径穿越"""
    name = Path(filename).name  # 去掉路径部分
    # 替换不允许的字符
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    # 去除首尾空格和点
    name = name.strip(". ")
    return name or "unnamed"
