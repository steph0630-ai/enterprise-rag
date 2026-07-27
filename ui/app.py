"""Streamlit Chat UI — 企业知识库问答 + NL2SQL 数据分析 + 历史搜索记录"""

import time
import streamlit as st
import requests
import os
import pandas as pd

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="企业知识库问答", page_icon="📚", layout="wide")

# ---- 初始化会话状态 ----
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "search_history" not in st.session_state:
    st.session_state.search_history = []  # [{query, answer_preview, intent, time}]

# ---- 标题 ----
st.title("📚 企业知识库问答系统")

# ---- 侧边栏 ----
with st.sidebar:
    # ===== 搜索历史 =====
    st.header("🕐 搜索记录")

    if st.session_state.search_history:
        if st.button("🗑 清空记录", use_container_width=True):
            st.session_state.search_history = []
            st.rerun()

        st.caption(f"共 {len(st.session_state.search_history)} 条记录")

    # 用 container 控制高度，避免撑爆侧边栏
    history_container = st.container(height=350)

    with history_container:
        for i, item in enumerate(reversed(st.session_state.search_history)):
            icon = "🤖" if item.get("intent") == "sql" else "📚"
            time_str = item.get("time", "").split(" ")[-1] if item.get("time") else ""
            label = f"{icon} {item['query'][:30]}{'...' if len(item['query']) > 30 else ''}"

            # 点击重新提问
            if st.button(label, key=f"hist_{i}", use_container_width=True,
                         help=f"{item.get('time', '')} | {item.get('answer_preview', '')[:80]}"):
                st.session_state._rerun_query = item["query"]
                st.rerun()

    st.divider()

    # ===== 操作面板 =====
    st.header("⚙️ 操作面板")

    st.subheader("📥 文档摄入")
    ingest_path = st.text_input("文档目录", value="./docs/samples")
    if st.button("🔄 开始摄入", use_container_width=True):
        with st.spinner("正在摄入文档..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/api/ingest/run",
                    json={"source_type": "local_fs", "path": ingest_path},
                    timeout=120,
                )
                data = resp.json()
                st.success(
                    f"完成！新增 {data['new_documents']} 篇，跳过 {data['skipped_documents']} 篇，"
                    f"共 {data['new_vector_count']} 条向量"
                )
                if data["errors"]:
                    st.warning(f"有 {data['failed_documents']} 篇失败:\n" + "\n".join(data["errors"][:5]))
            except Exception as e:
                st.error(f"摄入失败: {e}")

    st.subheader("📊 知识库")
    if st.button("刷新统计"):
        try:
            resp = requests.get(f"{API_BASE}/api/ingest/stats", timeout=5)
            d = resp.json()
            st.metric("向量总数", d["total_vectors"])
        except Exception:
            st.warning("无法连接后端")

    st.divider()

    st.subheader("💡 双模式说明")
    st.caption("""
    **📚 RAG**：文档类问题
    "Redis 怎么部署？"

    **🤖 SQL**：数据类问题
    "总共有多少订单？"

    系统自动判断
    """)


# ---- 处理历史记录点击重问 ----
def _run_query(prompt: str):
    """执行查询并返回结果，同时记录历史"""
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()

        try:
            resp = requests.post(
                f"{API_BASE}/api/chat/send",
                json={
                    "session_id": st.session_state.session_id,
                    "query": prompt,
                    "top_k": 5,
                },
                timeout=60,
            )
            data = resp.json()

            if data.get("session_id"):
                st.session_state.session_id = data["session_id"]

            answer = data["answer"]
            intent = data.get("intent", "rag")

            placeholder.markdown(answer)

            # NL2SQL 结果展示
            if intent == "sql" and data.get("nl2sql"):
                nl2sql = data["nl2sql"]
                if nl2sql.get("sql"):
                    with st.expander("🔍 查看 SQL 与数据"):
                        st.caption(f"SQL: `{nl2sql['sql']}`")
                        st.caption(
                            f"{nl2sql['sql_explanation']} | "
                            f"耗时 {nl2sql['execution_time_ms']:.0f}ms | "
                            f"返回 {nl2sql['row_count']} 行"
                        )
                        if nl2sql.get("columns") and nl2sql.get("rows"):
                            df = pd.DataFrame(nl2sql["rows"], columns=nl2sql["columns"])
                            st.dataframe(df, use_container_width=True)
                            if nl2sql.get("truncated"):
                                st.caption(f"⚠️ 结果已截断，仅展示前 {nl2sql['row_count']} 行")

            if intent == "sql":
                st.caption("🤖 数据查询模式 (NL2SQL)")
            else:
                st.caption("📚 文档检索模式 (RAG)")

            # 保存消息
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "intent": intent,
                "nl2sql": data.get("nl2sql"),
            })

            # 保存搜索历史（去重）
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            existing = [h for h in st.session_state.search_history if h["query"] == prompt]
            if not existing:
                st.session_state.search_history.append({
                    "query": prompt,
                    "answer_preview": answer[:100],
                    "intent": intent,
                    "time": now,
                })
            else:
                # 更新时间
                existing[0]["time"] = now

        except Exception as e:
            placeholder.error(f"请求失败: {e}")


# ---- 聊天区 ----
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("intent") == "sql" and msg.get("nl2sql"):
            st.markdown(msg["content"])
            nl2sql = msg["nl2sql"]
            if nl2sql.get("sql"):
                with st.expander("🔍 查看 SQL 与数据"):
                    st.caption(f"SQL: `{nl2sql['sql']}`")
                    st.caption(f"{nl2sql['sql_explanation']} | 耗时 {nl2sql['execution_time_ms']:.0f}ms")
                    if nl2sql.get("columns") and nl2sql.get("rows"):
                        df = pd.DataFrame(nl2sql["rows"], columns=nl2sql["columns"])
                        st.dataframe(df, use_container_width=True)
                        if nl2sql.get("truncated"):
                            st.caption(f"⚠️ 结果已截断，仅展示前 {nl2sql['row_count']} 行")
        else:
            st.markdown(msg["content"])


# ---- 输入处理 ----
# 来自历史记录点击的重问
if "_rerun_query" in st.session_state and st.session_state._rerun_query:
    prompt = st.session_state._rerun_query
    st.session_state._rerun_query = None
    _run_query(prompt)

# 正常输入
if prompt := st.chat_input("输入你的问题（文档类或数据类都可以）..."):
    _run_query(prompt)
