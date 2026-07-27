"""测试文档分块器"""

import pytest
from app.core.chunker import RecursiveCharacterChunker


class TestRecursiveCharacterChunker:
    """递归字符分块器测试"""

    def test_basic_chunking(self, markdown_content):
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=20)
        chunks = chunker.split(markdown_content)

        assert len(chunks) > 0
        for chunk in chunks:
            assert len(chunk) > 0

    def test_empty_text(self):
        chunker = RecursiveCharacterChunker()
        chunks = chunker.split("")
        assert len(chunks) == 0

    def test_short_text_single_chunk(self):
        chunker = RecursiveCharacterChunker(chunk_size=1000, chunk_overlap=50)
        chunks = chunker.split("这是一段很短的文本。")
        assert len(chunks) == 1
        assert chunks[0] == "这是一段很短的文本。"

    def test_chunk_boundaries_on_newlines(self):
        """验证优先在换行处分块"""
        text = "\n\n".join([f"段落 {i}: " + "x" * 50 for i in range(10)])
        chunker = RecursiveCharacterChunker(chunk_size=150, chunk_overlap=20)
        chunks = chunker.split(text)

        # 段落应该在换行边界处切分
        for chunk in chunks:
            # chunk 不应该以空白开头
            assert not chunk.startswith("\n")

    def test_overlap_between_chunks(self):
        """验证相邻 chunk 有重叠"""
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 10
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=30)
        chunks = chunker.split(text)

        if len(chunks) >= 2:
            # 前一个 chunk 的尾部应在后一个 chunk 的头部出现（重叠）
            tail = chunks[0][-10:]
            assert tail in chunks[1]

    def test_single_char_text(self):
        """极端短文本"""
        chunker = RecursiveCharacterChunker()
        chunks = chunker.split("A")
        assert len(chunks) == 1
        assert chunks[0] == "A"

    def test_default_constructor(self):
        """默认参数构造"""
        chunker = RecursiveCharacterChunker()
        assert chunker.chunk_size == 512
        assert chunker.chunk_overlap == 64
