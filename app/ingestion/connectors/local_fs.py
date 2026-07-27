"""本地文件系统连接器"""

import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone

from app.ingestion.connectors.base import BaseConnector, DocumentMeta, DocumentContent

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".md", ".txt", ".py", ".js", ".ts", ".html", ".json", ".yaml", ".yml", ".sql", ".java", ".go", ".rs"}


class LocalFSConnector(BaseConnector):
    """扫描本地目录，提取文档"""

    def __init__(self, root_path: str, source_name: str = "本地文档"):
        self.root = Path(root_path)
        if not self.root.exists():
            raise FileNotFoundError(f"目录不存在: {root_path}")
        self._source_name = source_name

    @property
    def source_type(self) -> str:
        return "local_fs"

    def list_documents(self, since: str | None = None) -> list[DocumentMeta]:
        """递归扫描所有支持的文件"""
        docs = []
        since_dt = datetime.fromisoformat(since) if since else None

        for file_path in self.root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if file_path.name.startswith("."):
                continue

            stat = file_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            # 增量：跳过未修改的文件
            if since_dt and mtime <= since_dt:
                continue

            rel_path = file_path.relative_to(self.root)
            docs.append(
                DocumentMeta(
                    doc_id=str(rel_path).replace("\\", "/"),
                    title=file_path.stem,
                    source_type=self.source_type,
                    source_name=self._source_name,
                    file_path=str(file_path.absolute()),
                    updated_at=mtime.isoformat(),
                    tags=[p.name for p in rel_path.parents if p.name][:-1],  # 目录名作为 tag
                )
            )

        logger.info("LocalFS scan: %s files found in %s", len(docs), self.root)
        return docs

    def fetch_content(self, meta: DocumentMeta) -> DocumentContent:
        """读取文件内容并计算 checksum"""
        path = Path(meta.file_path) if meta.file_path else self.root / meta.doc_id
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()

        checksum = hashlib.md5(raw.encode()).hexdigest()

        return DocumentContent(meta=meta, raw_text=raw, checksum=checksum)
