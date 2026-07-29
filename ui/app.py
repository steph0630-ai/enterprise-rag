"""Streamlit Chat UI — 企业知识库问答 + NL2SQL 数据分析 + 知识库管理"""

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
if "active_db" not in st.session_state:
    st.session_state.active_db = None

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

    history_container = st.container(height=200)

    with history_container:
        for i, item in enumerate(reversed(st.session_state.search_history)):
            icon = "🤖" if item.get("intent") == "sql" else "📚"
            time_str = item.get("time", "").split(" ")[-1] if item.get("time") else ""
            label = f"{icon} {item['query'][:30]}{'...' if len(item['query']) > 30 else ''}"

            if st.button(label, key=f"hist_{i}", use_container_width=True,
                         help=f"{item.get('time', '')} | {item.get('answer_preview', '')[:80]}"):
                st.session_state._rerun_query = item["query"]
                st.rerun()

    st.divider()

    # ===== 📄 上传文档 =====
    with st.expander("📄 上传文档 (RAG)", expanded=False):
        uploaded_file = st.file_uploader(
            "选择文档文件",
            type=["md", "txt", "markdown", "py", "js", "ts", "html", "htm",
                  "json", "yaml", "yml", "java", "go", "rs", "sql",
                  "cfg", "ini", "conf", "toml", "xml", "csv", "log"],
            key="doc_uploader",
            help="支持 Markdown、代码、配置文件、CSV 等文本格式，最大 20MB",
        )

        if uploaded_file is not None:
            if st.button("🔼 上传并索引", use_container_width=True, key="btn_upload_doc"):
                with st.spinner(f"正在处理 {uploaded_file.name} ..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                        resp = requests.post(
                            f"{API_BASE}/api/upload/document",
                            files=files,
                            timeout=120,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            st.success(f"✅ {data['message']}")
                            st.caption(f"文档ID: {data['doc_id']}，{data['chunks']} 个文本块")
                        else:
                            detail = resp.json().get("detail", resp.text)
                            st.error(f"上传失败: {detail}")
                    except Exception as e:
                        st.error(f"上传失败: {e}")

    # ===== 🗄️ 上传数据库 =====
    with st.expander("🗄️ 上传数据库 (NL2SQL)", expanded=False):
        uploaded_db = st.file_uploader(
            "选择 SQLite 数据库",
            type=["db", "sqlite", "sqlite3", "db3"],
            key="db_uploader",
            help="上传 .db 或 .sqlite 文件，最大 200MB",
        )

        if uploaded_db is not None:
            if st.button("🔼 上传数据库", use_container_width=True, key="btn_upload_db"):
                with st.spinner(f"正在上传 {uploaded_db.name} ..."):
                    try:
                        files = {"file": (uploaded_db.name, uploaded_db.getvalue())}
                        resp = requests.post(
                            f"{API_BASE}/api/upload/database",
                            files=files,
                            timeout=120,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            st.success(f"✅ {data['message']}")
                            st.caption(f"表: {', '.join(data['tables'][:8])}")
                            # 自动切换到新上传的数据库
                            st.session_state.active_db = data["filename"]
                        else:
                            detail = resp.json().get("detail", resp.text)
                            st.error(f"上传失败: {detail}")
                    except Exception as e:
                        st.error(f"上传失败: {e}")

    # ===== 📊 知识库管理 =====
    with st.expander("📊 知识库管理", expanded=False):
        tab_docs, tab_dbs = st.tabs(["📄 文档", "🗄️ 数据库"])

        # -- 文档列表 --
        with tab_docs:
            if st.button("🔄 刷新文档列表", use_container_width=True, key="btn_refresh_docs"):
                pass

            try:
                resp = requests.get(f"{API_BASE}/api/upload/documents", timeout=10)
                if resp.status_code == 200:
                    docs = resp.json()
                    if docs:
                        st.caption(f"共 {len(docs)} 个文档")
                        for doc in docs:
                            col1, col2 = st.columns([4, 1])
                            with col1:
                                st.caption(f"📄 {doc['filename']} ({doc['chunks']} chunks)")
                            with col2:
                                if st.button("🗑", key=f"del_doc_{doc['doc_id']}", help=f"删除 {doc['filename']}"):
                                    try:
                                        del_resp = requests.delete(
                                            f"{API_BASE}/api/upload/document",
                                            params={"filename": doc["filename"]},
                                            timeout=10,
                                        )
                                        if del_resp.status_code == 200:
                                            st.success(f"已删除 {doc['filename']}")
                                            st.rerun()
                                        else:
                                            st.error("删除失败")
                                    except Exception as e:
                                        st.error(f"删除失败: {e}")
                    else:
                        st.caption("暂无上传的文档")
                else:
                    st.caption("无法获取文档列表")
            except Exception:
                st.caption("⚠️ 无法连接后端")

        # -- 数据库列表 --
        with tab_dbs:
            if st.button("🔄 刷新数据库列表", use_container_width=True, key="btn_refresh_dbs"):
                pass

            try:
                resp = requests.get(f"{API_BASE}/api/upload/databases", timeout=10)
                if resp.status_code == 200:
                    dbs = resp.json()
                    if dbs:
                        st.caption(f"共 {len(dbs)} 个数据库")
                        for db in dbs:
                            is_active = db.get("is_active", False)
                            prefix = "🟢" if is_active else "⚫"
                            st.caption(
                                f"{prefix} **{db['filename']}** "
                                f"({db['size_bytes'] / 1024:.0f}KB, "
                                f"{len(db['tables'])} 张表)"
                            )
                            if db["tables"]:
                                st.caption(f"  表: {', '.join(db['tables'][:5])}"
                                           f"{'...' if len(db['tables']) > 5 else ''}")

                            col1, col2, col3 = st.columns([1, 1, 1])
                            with col1:
                                if not is_active:
                                    if st.button("🔁 切换", key=f"switch_db_{db['filename']}",
                                                 help=f"切换到 {db['filename']}"):
                                        try:
                                            sw_resp = requests.post(
                                                f"{API_BASE}/api/upload/database/switch",
                                                json={"filename": db["filename"]},
                                                timeout=10,
                                            )
                                            if sw_resp.status_code == 200:
                                                st.session_state.active_db = db["filename"]
                                                st.success(f"已切换到 {db['filename']}")
                                                st.rerun()
                                            else:
                                                st.error("切换失败")
                                        except Exception as e:
                                            st.error(f"切换失败: {e}")
                            with col2:
                                pass
                            with col3:
                                if st.button("🗑", key=f"del_db_{db['filename']}",
                                             help=f"删除 {db['filename']}"):
                                    try:
                                        del_resp = requests.delete(
                                            f"{API_BASE}/api/upload/database",
                                            params={"filename": db["filename"]},
                                            timeout=10,
                                        )
                                        if del_resp.status_code == 200:
                                            if st.session_state.active_db == db["filename"]:
                                                st.session_state.active_db = None
                                            st.success(f"已删除 {db['filename']}")
                                            st.rerun()
                                        else:
                                            st.error("删除失败")
                                    except Exception as e:
                                        st.error(f"删除失败: {e}")
                    else:
                        st.caption("暂无上传的数据库")
                else:
                    st.caption("无法获取数据库列表")
            except Exception:
                st.caption("⚠️ 无法连接后端")

    st.divider()

    # ===== 原有：文档摄入 =====
    with st.expander("📥 文档摄入 (目录扫描)", expanded=False):
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

    # ===== 知识库统计 =====
    st.subheader("📊 知识库统计")
    if st.button("🔄 刷新统计", use_container_width=True):
        try:
            resp = requests.get(f"{API_BASE}/api/ingest/stats", timeout=5)
            d = resp.json()
            st.metric("向量总数", d["total_vectors"])
            st.caption(f"BM25 文档: {d['bm25_documents']} | 词汇: {d['bm25_vocabulary']}")
        except Exception:
            st.warning("无法连接后端")

    # ===== NL2SQL 状态 =====
    try:
        resp = requests.get(f"{API_BASE}/api/upload/database/active", timeout=5)
        if resp.status_code == 200:
            active_info = resp.json()
            active_name = active_info.get("active_database")
            if active_name:
                st.caption(f"🟢 NL2SQL 当前库: **{active_name}**")
            else:
                st.caption("🟡 NL2SQL: 使用默认数据库")
    except Exception:
        pass

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
if "_rerun_query" in st.session_state and st.session_state._rerun_query:
    prompt = st.session_state._rerun_query
    st.session_state._rerun_query = None
    _run_query(prompt)

if prompt := st.chat_input("输入你的问题（文档类或数据类都可以）..."):
    _run_query(prompt)
