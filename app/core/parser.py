"""文档解析器 — 不同格式 → 统一纯文本"""

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentParser:
    """将常见文档格式解析为纯文本"""

    @staticmethod
    def parse(file_path: str) -> tuple[str, dict]:
        """
        解析文件，返回 (文本内容, 元数据)
        支持: .md, .txt, .py, .js, .ts, .json, .yaml, .html
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        content = ""

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except UnicodeDecodeError:
            # 二进制文件尝试 latin-1
            with open(path, "r", encoding="latin-1") as f:
                raw = f.read()
            logger.warning("File %s decoded with latin-1 fallback", path.name)

        if suffix == ".md":
            content = raw
        elif suffix in (".html", ".htm"):
            content = DocumentParser._strip_html(raw)
        elif suffix == ".json":
            content = raw  # JSON 直接保留原文，LLM 能理解
        elif suffix in (".yaml", ".yml"):
            content = raw
        elif suffix in (".py", ".js", ".ts", ".java", ".go", ".rs", ".sql"):
            content = f"```{suffix[1:]}\n{raw}\n```"
        else:
            content = raw  # 纯文本

        metadata = {
            "file_name": path.name,
            "file_path": str(path.absolute()),
            "file_type": suffix.lstrip("."),
            "file_size": path.stat().st_size,
        }

        return content, metadata

    @staticmethod
    def _strip_html(html: str) -> str:
        """简易 HTML → 纯文本（去掉标签）"""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
