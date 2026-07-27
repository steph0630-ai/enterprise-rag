"""DeepSeek LLM 封装 — OpenAI 兼容接口"""

import time
import logging
from openai import OpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """封装 DeepSeek API 调用，含重试、Token 计数"""

    def __init__(self):
        settings = get_settings()
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self.model = settings.deepseek_model
        self.max_retries = 3

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> str:
        """发送对话请求，失败自动重试（指数退避）"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                usage = response.usage
                logger.info(
                    "LLM call success — prompt_tokens=%s, completion_tokens=%s, total=%s",
                    usage.prompt_tokens if usage else "?",
                    usage.completion_tokens if usage else "?",
                    usage.total_tokens if usage else "?",
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning("LLM call attempt %s failed: %s — retrying in %ss", attempt + 1, e, wait)
                time.sleep(wait)

        raise RuntimeError(f"LLM call failed after {self.max_retries} retries: {last_error}")

    def chat_stream(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 2048):
        """流式对话 — 返回生成器"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
