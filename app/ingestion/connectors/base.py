"""数据源连接器基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class DocumentMeta:
    """文档元信息"""
    doc_id: str
    title: str
    source_type: str          # "local_fs", "confluence", ...
    source_name: str          # "技术 Wiki"
    file_path: str = ""
    url: str = ""
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class DocumentContent:
    meta: DocumentMeta
    raw_text: str
    checksum: str = ""        # 用于增量同步的 hash


class BaseConnector(ABC):
    """所有数据源连接器必须实现的接口"""

    @abstractmethod
    def list_documents(self, since: str | None = None) -> list[DocumentMeta]:
        """
        列出所有文档。since 不为空时只返回该时间之后更新的文档。
        since 格式：ISO 8601 时间戳
        """

    @abstractmethod
    def fetch_content(self, meta: DocumentMeta) -> DocumentContent:
        """根据元信息拉取文档正文"""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """数据源类型标识"""
