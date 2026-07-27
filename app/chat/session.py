"""会话管理 — 内存存储（生产可换 Redis）"""

import uuid
import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str       # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Session:
    session_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str):
        self.messages.append(Message(role=role, content=content))
        self.last_active = time.time()

    def get_history_str(self, max_turns: int = 5) -> str:
        """返回最近 N 轮对话的文本表示"""
        recent = self.messages[-(max_turns * 2) :]  # user + assistant 各算一轮
        lines = []
        for msg in recent:
            role_label = "用户" if msg.role == "user" else "助手"
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)


class SessionStore:
    """内存版会话存储"""

    def __init__(self, ttl_seconds: int = 3600):
        self.sessions: dict[str, Session] = {}
        self.ttl = ttl_seconds

    def create(self) -> Session:
        sid = str(uuid.uuid4())[:8]
        session = Session(session_id=sid)
        self.sessions[sid] = session
        logger.info("Session created: %s", sid)
        return session

    def get(self, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)
        if session:
            # 检查是否过期
            if time.time() - session.last_active > self.ttl:
                del self.sessions[session_id]
                return None
            return session
        return None

    def delete(self, session_id: str):
        self.sessions.pop(session_id, None)



# 全局单例
session_store = SessionStore()
