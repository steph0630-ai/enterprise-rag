"""测试会话管理"""

import time
import pytest
from app.chat.session import SessionStore, Session, Message


class TestSessionStore:
    """会话存储测试"""

    def test_create_session(self):
        store = SessionStore()
        session = store.create()
        assert isinstance(session, Session)
        assert len(session.session_id) == 8  # uuid4 前 8 位

    def test_get_session(self):
        store = SessionStore()
        session = store.create()
        retrieved = store.get(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    def test_session_expiry(self):
        """测试 TTL 过期"""
        store = SessionStore(ttl_seconds=0)  # 立即过期
        session = store.create()
        time.sleep(0.01)  # 确保过期
        retrieved = store.get(session.session_id)
        assert retrieved is None

    def test_session_not_expired(self):
        """正常 TTL 内会话可用"""
        store = SessionStore(ttl_seconds=3600)
        session = store.create()
        retrieved = store.get(session.session_id)
        assert retrieved is not None

    def test_add_message(self):
        session = Session(session_id="test-001")
        session.add_message("user", "你好")
        session.add_message("assistant", "你好！有什么可以帮你的？")

        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "你好"
        assert session.messages[1].role == "assistant"

    def test_get_history_str(self):
        session = Session(session_id="test-002")
        session.add_message("user", "订单服务超时时间是多少？")
        session.add_message("assistant", "默认超时是 30 秒。")

        history = session.get_history_str(max_turns=1)
        assert "用户:" in history or "用户：" in history
        assert "订单服务" in history
        assert "30 秒" in history

    def test_get_history_truncation(self):
        """验证只返回最近 N 轮"""
        session = Session(session_id="test-003")
        for i in range(10):
            session.add_message("user", f"问题 {i}")
            session.add_message("assistant", f"回答 {i}")

        history = session.get_history_str(max_turns=2)
        # 应该只包含最后 4 条消息（2 轮 = 4 条）
        assert "问题 0" not in history  # 最早的应该被截断
        assert "问题 9" in history       # 最新的应该保留

    def test_delete_session(self):
        store = SessionStore()
        session = store.create()
        store.delete(session.session_id)
        assert store.get(session.session_id) is None

    def test_nonexistent_session(self):
        store = SessionStore()
        assert store.get("nonexistent") is None

    def test_session_last_active_update(self):
        session = Session(session_id="test-004")
        old_time = session.last_active
        time.sleep(0.01)
        session.add_message("user", "新消息")
        assert session.last_active > old_time
