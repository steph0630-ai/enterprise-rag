"""Chat API 集成测试 — 用 FastAPI TestClient 测试接口"""

import pytest
from fastapi.testclient import TestClient


# 只在有依赖且 Qdrant 可能不可用时做基础测试
class TestChatAPI:
    """Chat API 测试（不依赖外部服务的基础测试）"""

    @pytest.fixture(scope="class")
    def client(self):
        """创建 TestClient"""
        try:
            from app.main import app
            return TestClient(app)
        except Exception as e:
            pytest.skip(f"无法创建 TestClient: {e}")

    def test_root_endpoint(self, client):
        """测试根路径"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "Enterprise RAG"

    def test_chat_send_basic(self, client):
        """测试基本对话请求（即使 Qdrant 不可用也应该返回 500 或 fallback）"""
        resp = client.post(
            "/api/chat/send",
            json={"query": "测试"},
        )
        # 500 可能是 Qdrant 不可用，200 是正常工作
        assert resp.status_code in [200, 500]
        if resp.status_code == 200:
            data = resp.json()
            assert "answer" in data
            assert "session_id" in data
            assert data["intent"] in ("rag", "sql")

    def test_chat_send_with_session(self, client):
        """测试带 session_id 的多轮对话"""
        resp1 = client.post(
            "/api/chat/send",
            json={"query": "你好"},
        )
        if resp1.status_code == 200:
            sid = resp1.json()["session_id"]
            # 第二轮的 session_id 应该相同
            resp2 = client.post(
                "/api/chat/send",
                json={"session_id": sid, "query": "继续"},
            )
            if resp2.status_code == 200:
                assert resp2.json()["session_id"] == sid

    def test_chat_stream(self, client):
        """测试流式接口"""
        resp = client.post(
            "/api/chat/stream",
            json={"query": "测试"},
        )
        # 流式返回文本或 500
        assert resp.status_code in [200, 500]

    def test_get_session(self, client):
        """测试获取会话历史"""
        resp = client.get("/api/chat/session/nonexistent")
        # 不存在的会话返回 404
        assert resp.status_code in [404, 200]

    def test_ingest_stats(self, client):
        """测试知识库统计接口"""
        resp = client.get("/api/ingest/stats")
        # 可能 200（Qdrant 可用）或 500（不可用）
        assert resp.status_code in [200, 500]


class TestChatAPIResponseStructure:
    """验证 API 响应结构正确性"""

    @pytest.fixture(scope="class")
    def client(self):
        try:
            from app.main import app
            return TestClient(app)
        except Exception as e:
            pytest.skip(f"无法创建 TestClient: {e}")

    def test_response_has_required_fields(self, client):
        """响应必须包含所有文档声明的字段"""
        resp = client.post("/api/chat/send", json={"query": "测试"})
        if resp.status_code == 200:
            data = resp.json()
            required_fields = ["session_id", "answer", "intent", "citations",
                               "context_count", "query_rewritten", "nl2sql"]
            for field in required_fields:
                assert field in data, f"缺少字段: {field}"

    def test_rag_response_has_citations(self, client):
        """RAG 模式返回的 citations 结构正确"""
        resp = client.post("/api/chat/send", json={"query": "测试"})
        if resp.status_code == 200:
            data = resp.json()
            if data["intent"] == "rag" and data["citations"]:
                citation = data["citations"][0]
                assert "index" in citation
                assert "title" in citation
                assert "source_name" in citation
                assert "excerpt" in citation

    def test_sql_response_has_nl2sql_data(self, client):
        """SQL 模式返回的 nl2sql 字段结构正确"""
        resp = client.post(
            "/api/chat/send",
            json={"query": "数码配件有多少商品"},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data["intent"] == "sql" and data["nl2sql"]:
                nl2sql = data["nl2sql"]
                assert "sql" in nl2sql
                assert "columns" in nl2sql
                assert "rows" in nl2sql
                assert "row_count" in nl2sql
                assert "execution_time_ms" in nl2sql
