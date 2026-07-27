"""多轮查询改写：将追问改写为完整独立的检索查询"""

import logging

from app.core.llm import LLMClient

logger = logging.getLogger(__name__)


QUERY_REWRITE_PROMPT = """你是一个查询改写助手。你的任务是把用户在多轮对话中的追问，改写为一个完整、独立、适合检索的查询语句。

## 规则
1. 补全追问中省略的主语、宾语、上下文
2. 保持原意，不要添加用户没问的内容
3. 只返回改写后的查询语句，不要解释

## 对话历史
{history}

## 用户追问
{question}

## 改写后的查询"""


class QueryRewriter:
    """将上下文依赖的追问改写为独立 query"""

    def __init__(self):
        self.llm = LLMClient()

    def rewrite(self, question: str, history: str) -> str:
        """
        改写追问

        Args:
            question: 用户当前输入
            history: 最近几轮对话的文本表示

        Returns:
            改写后的独立查询，如果不需要改写则返回原问题
        """
        # 如果问题已经很长（>15 字），大概率不需要改写
        if len(question) > 15 and ("?" in question or "？" in question or "怎么" in question):
            return question

        # 如果问题不短且包含具体名词，也不需要改写
        if len(question) > 10:
            return question

        # 短问题很可能是追问，需要改写
        try:
            rewritten = self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": QUERY_REWRITE_PROMPT.format(history=history, question=question),
                }],
                temperature=0.2,
                max_tokens=256,
            )
            rewritten = rewritten.strip().strip('"').strip("'")
            logger.info("Query rewritten: '%s' → '%s'", question, rewritten)
            return rewritten if rewritten else question
        except Exception as e:
            logger.warning("Query rewrite failed, using original: %s", e)
            return question
