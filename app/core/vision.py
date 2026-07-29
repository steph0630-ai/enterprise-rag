"""视觉理解服务 — OCR 提取图片文字（EasyOCR 本地识别 + 可选远程 Vision API）"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# EasyOCR 全局单例（懒加载，首次加载会下载模型）
_ocr_reader = None


def _get_ocr_reader():
    """懒加载 EasyOCR reader（首次调用自动下载中文模型）"""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        logger.info("Loading EasyOCR model (chinese + english)...")
        _ocr_reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        logger.info("EasyOCR model loaded")
    return _ocr_reader


class VisionService:
    """图片 → 文本：优先用本地 EasyOCR，失败回退到远程 Vision API"""

    def describe_image(self, image_path: str | Path) -> str:
        path = Path(image_path)
        suffix = path.suffix.lower()
        file_size = path.stat().st_size

        # ── 方案 A: 本地 EasyOCR ──
        try:
            text = self._ocr_image(str(path))
            if text.strip():
                logger.info("OCR success: %s → %d chars", path.name, len(text))
                return f"[图片文字识别: {path.name}]\n{text}"
        except Exception as e:
            logger.warning("OCR failed for %s: %s, trying vision API...", path.name, e)

        # ── 方案 B: 远程 Vision API ──
        try:
            text = self._vision_api(str(path))
            if text.strip():
                logger.info("Vision API success: %s → %d chars", path.name, len(text))
                return f"[AI 图片描述: {path.name}]\n{text}"
        except Exception as e:
            logger.warning("Vision API also failed for %s: %s", path.name, e)

        # ── 方案 C: 兜底元数据 ──
        try:
            from PIL import Image
            img = Image.open(path)
            info = (
                f"文件名: {path.name}\n"
                f"尺寸: {img.size[0]}x{img.size[1]} 像素\n"
                f"格式: {img.format}\n"
                f"模式: {img.mode}\n"
                f"大小: {file_size / 1024:.1f}KB"
            )
            return f"[图片基本信息: {path.name}]\n{info}\n\n(文字识别和 AI 视觉均不可用，仅索引了元数据)"
        except Exception:
            return f"[图片: {path.name}]\n文件大小: {file_size / 1024:.1f}KB\n格式: {suffix}"

    def describe_image_bytes(self, image_bytes: bytes, filename: str = "image.png") -> str:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
        try:
            return self.describe_image(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ── OCR ──

    @staticmethod
    def _ocr_image(image_path: str) -> str:
        """用 EasyOCR 提取图片文字（PIL 加载避免 OpenCV 中文路径问题）"""
        import numpy as np
        from PIL import Image

        reader = _get_ocr_reader()
        # 用 PIL 加载再转 numpy，避免 OpenCV imread 的中文路径问题
        img = Image.open(image_path)
        img_np = np.array(img)
        results = reader.readtext(img_np, detail=0)  # detail=0 只返回文字
        if not results:
            return ""
        return "\n".join(results)

    # ── Remote Vision API (fallback) ──

    @staticmethod
    def _vision_api(image_path: str) -> str:
        """调用远程多模态 LLM 描述图片"""
        import base64
        import io

        from PIL import Image
        from openai import OpenAI
        from app.config import get_settings

        settings = get_settings()

        # 压缩图片
        img = Image.open(image_path)
        if max(img.size) > 1568:
            ratio = 1568 / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        image_bytes = buf.getvalue()

        # data URL
        suffix = Path(image_path).suffix.lower()
        mime = "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"

        client = OpenAI(
            api_key=settings.vision_api_key or settings.deepseek_api_key,
            base_url=settings.vision_base_url,
        )

        response = client.chat.completions.create(
            model=settings.vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "请提取并转录图片中所有可见的文字内容。如果是图表，请描述数据。请用中文。"},
                ],
            }],
            temperature=0.1,
            max_tokens=1024,
        )
        return response.choices[0].message.content or ""
