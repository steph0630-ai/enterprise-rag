"""FastAPI 入口"""

import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, ingest

# 日志配置
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

app = FastAPI(
    title="Enterprise RAG — 企业知识库问答 + NL2SQL 系统",
    version="0.2.0",
    description="多源文档摄入 + 混合检索 + Reranker + 多轮对话 + NL2SQL",
)

# CORS
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8501,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat.router)
app.include_router(ingest.router)


@app.get("/")
def root():
    return {
        "service": "Enterprise RAG",
        "version": "0.2.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    """存活检查"""
    return {"status": "healthy"}


@app.get("/ready")
def ready():
    """就绪检查 — 验证 Qdrant 是否可连接"""
    try:
        import httpx
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        resp = httpx.get(f"{qdrant_url}/collections", timeout=5)
        qdrant_ok = resp.status_code == 200
    except Exception:
        qdrant_ok = False

    if qdrant_ok:
        return {"status": "ready", "qdrant": "connected"}
    else:
        return {"status": "not_ready", "qdrant": "disconnected"}
