"""文档分块策略"""

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    content: str
    metadata: dict = field(default_factory=dict)


class RecursiveCharacterChunker:
    """
    递归字符分块器：
    按优先级尝试分隔符（段落 → 行 → 句号 → 空格 → 字符），
    在自然边界处切分，保证 chunk_size + overlap。
    """

    SEPARATORS = ["\n\n", "\n", "。", ". ", ".", " ", ""]

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str) -> list[str]:
        """主入口：将文本切分为 chunk 列表"""
        return self._split_recursive(text, self.SEPARATORS)

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """递归切分"""
        sep = separators[0]
        remaining_seps = separators[1:]

        if sep:
            segments = text.split(sep)
        else:
            # 最后兜底：逐字符切分
            segments = list(text)

        chunks = []
        current = ""

        for segment in segments:
            segment_with_sep = segment if not sep else segment
            combined = current + (sep if current else "") + segment_with_sep

            if len(combined) <= self.chunk_size:
                current = combined
            else:
                # 当前 segment 放不下
                if current:
                    chunks.append(current)

                if len(segment_with_sep) > self.chunk_size:
                    # segment 本身太大，递归切分
                    if remaining_seps:
                        sub_chunks = self._split_recursive(segment_with_sep, remaining_seps)
                        chunks.extend(sub_chunks)
                    else:
                        # 已经没有更细的分隔符了，硬切
                        chunks.append(segment_with_sep[: self.chunk_size])
                else:
                    current = segment_with_sep

        if current:
            chunks.append(current)

        return chunks

    def split_with_overlap(self, text: str) -> list[str]:
        """切分后添加重叠上下文"""
        chunks = self.split(text)
        if len(chunks) <= 1:
            return chunks

        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            # 从前一个 chunk 末尾取 overlap 长度的文本拼到当前 chunk 前面
            overlap_text = prev[-self.chunk_overlap :] if len(prev) > self.chunk_overlap else prev
            overlapped.append(overlap_text + "\n" + curr)

        return overlapped

    def chunk_document(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        """完整流程：文本 → 带重叠的 chunk 列表，附带元数据"""
        chunk_texts = self.split_with_overlap(text)
        meta = metadata or {}
        return [
            Chunk(
                content=ct,
                metadata={
                    **meta,
                    "chunk_index": i,
                    "total_chunks": len(chunk_texts),
                },
            )
            for i, ct in enumerate(chunk_texts)
        ]
