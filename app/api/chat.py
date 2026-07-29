"""对话 API — 意图路由 + 多轮查询改写 + Reranker 精排 + NL2SQL"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import get_settings, PROJECT_ROOT
from app.generation.generator import Generator
from app.chat.session import session_store
from app.chat.query_rewriter import QueryRewriter
from app.nl2sql.pipeline import NL2SQLPipeline
from app.nl2sql.db_manager import get_db_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

# 初始化
generator = Generator(enable_rerank=False)  # 关闭 Reranker 提速，混合检索+RRF 已够准
rewriter = QueryRewriter()

# NL2SQL pipeline（懒加载 + 支持动态切换数据库）
_nl2sql: NL2SQLPipeline | None = None
_nl2sql_db_path: str | None = None  # 记录当前 pipeline 使用的 db 路径


def reset_nl2sql():
    """重置 NL2SQL pipeline（数据库切换后调用）"""
    global _nl2sql, _nl2sql_db_path
    _nl2sql = None
    _nl2sql_db_path = None
    logger.info("NL2SQL pipeline reset for database switch")


def _get_nl2sql() -> NL2SQLPipeline | None:
    """懒加载 NL2SQL pipeline，自动使用用户选择的数据库"""
    global _nl2sql, _nl2sql_db_path

    # 获取当前活跃数据库路径
    db_manager = get_db_manager()
    db_path = db_manager.active_db_path

    # 如果路径没变且已初始化，直接返回
    if _nl2sql is not None and _nl2sql_db_path == db_path:
        return _nl2sql

    # 回退到配置文件中的路径
    if not db_path:
        settings = get_settings()
        db_path = settings.sqlite_db_path
        if not db_path:
            db_path = str(PROJECT_ROOT / "data" / "business.db")

    if Path(db_path).exists():
        _nl2sql = NL2SQLPipeline(db_path)
        _nl2sql_db_path = db_path
        logger.info("NL2SQL pipeline initialized: %s", db_path)
    else:
        logger.warning("NL2SQL database not found at %s, NL2SQL disabled", db_path)
        _nl2sql = None
        _nl2sql_db_path = None

    return _nl2sql


# ── Request / Response ──

class ChatRequest(BaseModel):
    session_id: str | None = None
    query: str
    top_k: int = 5


class CitationOut(BaseModel):
    index: int
    title: str
    source_name: str
    excerpt: str


class NL2SQLResultOut(BaseModel):
    sql: str | None = None
    sql_explanation: str = ""
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    intent: str  # "rag" | "sql"
    citations: list[CitationOut] = []
    context_count: int = 0
    query_rewritten: str | None = None
    nl2sql: NL2SQLResultOut | None = None


# ── Routes ──

@router.post("/send", response_model=ChatResponse)
def send_message(req: ChatRequest):
    """智能对话：自动路由到 RAG 或 NL2SQL"""
    session = session_store.get(req.session_id) if req.session_id else None
    if not session:
        session = session_store.create()

    # 查询改写
    history = session.get_history_str(max_turns=3)
    rewritten = rewriter.rewrite(req.query, history) if history else req.query

    session.add_message("user", req.query)

    # ── Step 1: 意图路由 ──
    nl2sql = _get_nl2sql()
    intent = "rag"

    if nl2sql:
        route_result = nl2sql.route_only(rewritten)
        intent = route_result["intent"]
        logger.info("Intent: %s (confidence=%.2f, reason=%s)", intent, route_result["confidence"], route_result["reason"])

    try:
        if intent == "sql" and nl2sql:
            # ── NL2SQL 路径 ──
            nlsql_result = nl2sql.answer(rewritten)

            session.add_message("assistant", nlsql_result.answer)

            nl2sql_out = NL2SQLResultOut(
                sql=nlsql_result.sql,
                sql_explanation=nlsql_result.sql_explanation,
                columns=nlsql_result.columns,
                rows=nlsql_result.rows,
                row_count=nlsql_result.row_count,
                truncated=nlsql_result.truncated,
                execution_time_ms=nlsql_result.execution_time_ms,
            )

            return ChatResponse(
                session_id=session.session_id,
                answer=nlsql_result.answer,
                intent="sql",
                citations=[],
                context_count=nlsql_result.row_count,
                query_rewritten=rewritten if rewritten != req.query else None,
                nl2sql=nl2sql_out,
            )
        else:
            # ── RAG 路径 ──
            if rewritten != req.query:
                result = generator.answer_with_rewrite(req.query, rewritten, top_k=req.top_k)
            else:
                result = generator.answer(req.query, top_k=req.top_k)

            session.add_message("assistant", result.answer)

            return ChatResponse(
                session_id=session.session_id,
                answer=result.answer,
                intent="rag",
                citations=[
                    CitationOut(
                        index=c.index,
                        title=c.title,
                        source_name=c.source_name,
                        excerpt=c.content_excerpt,
                    )
                    for c in result.citations
                ],
                context_count=len(result.context_used),
                query_rewritten=rewritten if rewritten != req.query else None,
            )
    except Exception as e:
        logger.error("Chat failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"回答生成失败: {e}")


@router.post("/stream")
def send_message_stream(req: ChatRequest):
    """流式对话（仅 RAG，NL2SQL 不走流式）"""

    def generate():
        session = session_store.get(req.session_id) if req.session_id else None
        if not session:
            session = session_store.create()

        history = session.get_history_str(max_turns=3)
        rewritten = rewriter.rewrite(req.query, history) if history else req.query

        session.add_message("user", req.query)

        try:
            full_answer = ""
            for token in generator.answer_stream(req.query, top_k=req.top_k):
                full_answer += token
                yield token
            session.add_message("assistant", full_answer)
        except Exception as e:
            logger.error("Stream failed: %s", e, exc_info=True)
            yield f"\n[错误] {e}"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@router.get("/session/{session_id}")
def get_session(session_id: str):
    """获取会话历史"""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {
        "session_id": session.session_id,
        "messages": [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in session.messages],
    }
