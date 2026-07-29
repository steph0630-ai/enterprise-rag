"""语义感知分块器 — 类型标记 + 重叠 + 去重"""

import re
import hashlib
from dataclasses import dataclass, field

# 常见页眉页脚模式（会被去重）
BOILERPLATE_PATTERNS = [
    r"^第\s*\d+\s*页\s*(共\s*\d+\s*页)?$",
    r"^Page\s+\d+\s+(of\s+\d+)?$",
    r"^版权所有.*$",
    r"^Confidential.*$",
    r"^\d+/\d+/\d+.*$",
    r"^第\s*[一二三四五六七八九十百千]+\s*章\s*$",
]


@dataclass
class Chunk:
    content: str
    metadata: dict = field(default_factory=dict)


class RecursiveCharacterChunker:
    """递归字符分块 + 语义类型标记 + 页眉页脚去重"""

    SEPARATORS = ["\n\n", "\n", "。", ". ", ".", " ", ""]
    CHUNK_TYPES = {
        "code": [r"```", r"def\s", r"function\s", r"class\s", r"import\s", r"from\s", r"SELECT\s", r"CREATE\s"],
        "table": [r"\|.*\|.*\|", r"\[表格\]", r"header:.*row:", r"^\s*\|"],
        "list": [r"^\s*[-*+]\s", r"^\s*\d+[\.\)]\s"],
        "heading": [r"^#{1,6}\s", r"^第[一二三四五六七八九十百千]+[章节条款]"],
        "ocr_text": [r"\(OCR识别", r"置信度:", r"\[OCR补充\]"],
    }

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._seen_hashes: set[str] = set()

    def split(self, text: str) -> list[str]:
        return self._split_recursive(text, self.SEPARATORS)

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        sep = separators[0]
        remaining_seps = separators[1:]

        if sep:
            segments = text.split(sep)
        else:
            segments = list(text)

        chunks = []
        current = ""

        for segment in segments:
            segment_with_sep = segment if not sep else segment
            combined = current + (sep if current else "") + segment_with_sep

            if len(combined) <= self.chunk_size:
                current = combined
            else:
                if current:
                    chunks.append(current)
                if len(segment_with_sep) > self.chunk_size:
                    if remaining_seps:
                        sub_chunks = self._split_recursive(segment_with_sep, remaining_seps)
                        chunks.extend(sub_chunks)
                    else:
                        chunks.append(segment_with_sep[:self.chunk_size])
                else:
                    current = segment_with_sep

        if current:
            chunks.append(current)

        return chunks

    def split_with_overlap(self, text: str) -> list[str]:
        chunks = self.split(text)
        if len(chunks) <= 1:
            return chunks

        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            overlap_text = prev[-self.chunk_overlap:] if len(prev) > self.chunk_overlap else prev
            overlapped.append(overlap_text + "\n" + curr)

        return overlapped

    def chunk_document(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        """完整分块流程：分块 → 类型标记 → 去重 → 元数据"""
        chunk_texts = self.split_with_overlap(text)
        meta = metadata or {}

        chunks = []
        for i, ct in enumerate(chunk_texts):
            # 跳过纯页眉页脚
            if self._is_boilerplate(ct):
                continue

            # 去重
            chunk_hash = hashlib.md5(ct.encode()).hexdigest()[:12]
            if chunk_hash in self._seen_hashes:
                continue
            self._seen_hashes.add(chunk_hash)

            # 语义类型
            chunk_type = self._classify_chunk(ct)

            chunks.append(Chunk(
                content=ct,
                metadata={
                    **meta,
                    "chunk_index": i,
                    "total_chunks": len(chunk_texts),
                    "chunk_type": chunk_type,
                    "chunk_hash": chunk_hash,
                },
            ))

        return chunks

    def reset_dedup(self):
        """重置去重缓存（跨文档不共享）"""
        self._seen_hashes.clear()

    # ── 分块类型分类 ──

    @staticmethod
    def _classify_chunk(text: str) -> str:
        """启发式判断 chunk 的语义类型"""
        for ctype, patterns in RecursiveCharacterChunker.CHUNK_TYPES.items():
            for pat in patterns:
                if re.search(pat, text, re.MULTILINE):
                    return ctype
        return "text"

    # ── 页眉页脚检测 ──

    @staticmethod
    def _is_boilerplate(text: str) -> bool:
        """判断是否为无意义的页眉页脚"""
        stripped = text.strip()
        if len(stripped) < 10:
            return True
        if len(stripped) < 30:
            for pat in BOILERPLATE_PATTERNS:
                if re.match(pat, stripped):
                    return True
        return False
