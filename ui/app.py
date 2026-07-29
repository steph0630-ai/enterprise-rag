"""Streamlit Chat UI — 企业知识库问答 + NL2SQL 数据分析 + 知识库管理
De-AI UI: warm editorial palette, layered shadows, irregular radii, micro-interactions.
"""

import time
import streamlit as st
import requests
import os
import pandas as pd

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="企业知识库问答", page_icon="📚", layout="wide")

# ═══════════════════════════════════════════════════════════════
#  Custom CSS — De-AI UI: 7 dimensions applied
# ═══════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* ── 0. CSS Variables ─────────────────────────────────────── */
:root {
  --bg: #FBF9F6;
  --surface: #F3EFEA;
  --text: #1A1817;
  --muted: #78716C;
  --primary: #E85D2C;
  --primary-hover: #D14D1C;
  --accent: #2D7D6F;
  --border: #E7E0D8;
  --border-strong: #D6CFC5;
  --shadow-sm: 0 1px 2px rgba(26,24,23,0.04), 0 2px 6px rgba(26,24,23,0.03);
  --shadow-md: 0 1px 2px rgba(26,24,23,0.05), 0 4px 12px rgba(26,24,23,0.04), 0 12px 32px rgba(26,24,23,0.05);
  --shadow-lg: 0 2px 4px rgba(26,24,23,0.04), 0 8px 24px rgba(26,24,23,0.06), 0 24px 56px rgba(26,24,23,0.06);
  --shadow-button: 0 1px 2px rgba(26,24,23,0.08), 0 2px 8px rgba(232,93,44,0.12);
  --shadow-button-hover: 0 2px 4px rgba(26,24,23,0.08), 0 4px 16px rgba(232,93,44,0.18);
  --radius-sm: 3px;
  --radius-md: 6px;
  --radius-lg: 10px;
  --radius-xl: 14px;
  --radius-2xl: 16px;
  --transition-hover: 200ms cubic-bezier(0.34, 1.56, 0.64, 1);
  --transition-out: 180ms cubic-bezier(0.4, 0, 0.2, 1);
}

/* ── 1. Global / Typography ───────────────────────────────── */
.stApp {
  background-color: var(--bg);
}

/* Noise texture overlay on main bg */
.stApp::before {
  content: '';
  position: fixed;
  inset: 0;
  opacity: 0.012;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  pointer-events: none;
  z-index: 9999;
}

/* Typography — system font stack, no Inter */
html, body, [data-testid="stAppViewContainer"], .stMarkdown, .stText {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans SC", sans-serif !important;
  color: var(--text);
}

/* Headings */
h1 {
  font-size: 1.75rem !important;
  font-weight: 600 !important;
  letter-spacing: -0.01em !important;
  color: var(--text) !important;
  line-height: 1.25 !important;
  padding-bottom: 0.25rem !important;
}
h2 {
  font-size: 1.25rem !important;
  font-weight: 600 !important;
  letter-spacing: -0.005em !important;
  color: var(--text) !important;
}
h3 {
  font-size: 1rem !important;
  font-weight: 600 !important;
  color: var(--muted) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.04em !important;
  font-size: 0.7rem !important;
}
/* Caption / muted text */
[data-testid="stCaptionContainer"], .stCaption {
  color: var(--muted) !important;
  font-size: 0.8rem !important;
  line-height: 1.5 !important;
}

/* ── 2. Sidebar ────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background-color: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] h2 {
  font-size: 0.75rem !important;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  font-weight: 600;
}
[data-testid="stSidebar"] h3 {
  font-size: 0.7rem !important;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  font-weight: 600;
}

/* ── 3. Buttons — irregular radius, layered shadow, spring hover ── */
.stButton > button {
  border-radius: var(--radius-md) !important;   /* 6px, not 8px */
  border: 1px solid var(--border) !important;
  background: #FFF !important;
  color: var(--text) !important;
  box-shadow: var(--shadow-sm) !important;
  font-size: 0.82rem !important;
  font-weight: 500 !important;
  padding: 0.4rem 1rem !important;
  transition:
    background 150ms ease,
    transform var(--transition-hover),
    box-shadow 250ms ease !important;
}
.stButton > button:hover {
  background: var(--bg) !important;
  border-color: var(--border-strong) !important;
  transform: scale(1.015);
  box-shadow: var(--shadow-md) !important;
}
.stButton > button:active {
  transform: scale(0.985);
  box-shadow: var(--shadow-sm) !important;
  transition: transform 80ms ease, box-shadow 80ms ease !important;
}

/* Primary-style buttons (use_container_width prominent ones) */
.stButton > button[kind="primary"], .stButton > button:has(+ .stSpinner) {
  /* fallback — Streamlit doesn't have kind= attr in older versions */
}

/* ── 4. Inputs & File Uploaders ────────────────────────────── */
input, textarea, [data-testid="stTextInput"] input {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border) !important;
  background: #FFF !important;
  font-size: 0.85rem !important;
  padding: 0.5rem 0.75rem !important;
  transition: border-color 200ms ease, box-shadow 200ms ease !important;
}
input:focus, textarea:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px rgba(232,93,44,0.1) !important;
  outline: none !important;
}

/* File uploader drop zone */
[data-testid="stFileUploaderDropzone"] {
  border-radius: var(--radius-lg) !important;
  border: 1.5px dashed var(--border-strong) !important;
  background: var(--bg) !important;
  transition: border-color 200ms ease, background 200ms ease !important;
}
[data-testid="stFileUploaderDropzone"]:hover {
  border-color: var(--primary) !important;
  background: rgba(232,93,44,0.02) !important;
}

/* ── 5. Chat Messages — layered shadows, irregular radii ───── */
[data-testid="stChatMessage"] {
  border-radius: var(--radius-lg) !important;   /* 10px, not 8px */
  padding: 1rem 1.25rem !important;
  margin-bottom: 0.75rem !important;
}

/* User message */
[data-testid="stChatMessage"][data-testid="stChatMessage"]:nth-of-type(odd) {
  background: #FFF !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow-sm) !important;
}

/* Assistant message */
[data-testid="stChatMessage"][data-testid="stChatMessage"]:nth-of-type(even) {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow-sm) !important;
}

/* Chat message content */
[data-testid="stChatMessage"] p {
  line-height: 1.6 !important;
  font-size: 0.9rem !important;
}

/* Chat input */
[data-testid="stChatInput"] textarea {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border-strong) !important;
  background: #FFF !important;
  box-shadow: var(--shadow-sm) !important;
  transition: border-color 200ms ease, box-shadow 200ms ease !important;
}
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px rgba(232,93,44,0.08) !important;
}

/* ── 6. Expanders — cleaned up, no rounded-rect slab ───────── */
[data-testid="stExpander"] {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;   /* 10px */
  background: #FFF !important;
  box-shadow: var(--shadow-sm) !important;
  margin-bottom: 0.5rem !important;
  overflow: hidden;
}
[data-testid="stExpander"] summary {
  font-size: 0.82rem !important;
  font-weight: 500 !important;
  color: var(--text) !important;
  padding: 0.6rem 0.9rem !important;
}
[data-testid="stExpander"] summary:hover {
  background: var(--bg) !important;
}

/* ── 7. Metrics — card feel ────────────────────────────────── */
[data-testid="stMetric"] {
  background: #FFF;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0.9rem 1.1rem;
  box-shadow: var(--shadow-sm);
}
[data-testid="stMetric"] label {
  font-size: 0.7rem !important;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  font-weight: 600 !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
  font-size: 1.6rem !important;
  font-weight: 600 !important;
  color: var(--text) !important;
}

/* ── 8. Dataframes — refined borders, not the default grid ─── */
[data-testid="stDataFrame"] {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border) !important;
  overflow: hidden;
}
[data-testid="stDataFrame"] table {
  font-size: 0.8rem !important;
}
[data-testid="stDataFrame"] th {
  background: var(--surface) !important;
  font-weight: 600 !important;
  color: var(--muted) !important;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  font-size: 0.7rem !important;
  padding: 0.5rem 0.75rem !important;
}
[data-testid="stDataFrame"] td {
  padding: 0.4rem 0.75rem !important;
  border-bottom: 1px solid var(--border) !important;
}

/* ── 9. Dividers — hairline, tinted ────────────────────────── */
hr, [data-testid="stDivider"] {
  border-color: var(--border) !important;
  opacity: 0.6 !important;
  margin: 0.75rem 0 !important;
}

/* ── 10. Success / Warning / Error — softer tones ──────────── */
[data-testid="stSuccess"] {
  background: rgba(45,125,111,0.08) !important;
  border: 1px solid rgba(45,125,111,0.2) !important;
  border-radius: var(--radius-md) !important;
  color: #1E5A4E !important;
}
[data-testid="stWarning"] {
  background: rgba(232,93,44,0.06) !important;
  border: 1px solid rgba(232,93,44,0.15) !important;
  border-radius: var(--radius-md) !important;
  color: #8B3A1A !important;
}
[data-testid="stError"] {
  background: rgba(200,50,30,0.06) !important;
  border: 1px solid rgba(200,50,30,0.15) !important;
  border-radius: var(--radius-md) !important;
}

/* ── 11. Scrollbar — minimal ───────────────────────────────── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 9999px;
}
::-webkit-scrollbar-thumb:hover { background: var(--muted); }

/* ── 12. Spinner ───────────────────────────────────────────── */
[data-testid="stSpinner"] {
  color: var(--primary) !important;
}

/* ── 13. Sidebar scroll container (search history) ─────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: #FFF;
}

/* ── 14. Main content area — breathing room ────────────────── */
section.main > div {
  padding-top: 2rem !important;
  padding-bottom: 3rem !important;
}

/* ── 15. Code blocks ───────────────────────────────────────── */
code {
  font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.82rem !important;
  background: var(--surface) !important;
  border-radius: var(--radius-sm) !important;
  padding: 0.15rem 0.35rem !important;
  color: var(--primary) !important;
}
pre {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--border) !important;
  background: #FFF !important;
  box-shadow: var(--shadow-sm) !important;
}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
#  Session State
# ═══════════════════════════════════════════════════════════════
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "search_history" not in st.session_state:
    st.session_state.search_history = []
if "active_db" not in st.session_state:
    st.session_state.active_db = None


# ═══════════════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    # ── Search History ──
    st.header("搜索记录")

    if st.session_state.search_history:
        c1, c2 = st.columns([3, 1])
        with c2:
            if st.button("清空", use_container_width=True, key="clear_history"):
                st.session_state.search_history = []
                st.rerun()

    history_container = st.container(height=200)
    with history_container:
        if st.session_state.search_history:
            for i, item in enumerate(reversed(st.session_state.search_history)):
                intent_label = "SQL" if item.get("intent") == "sql" else "RAG"
                time_str = item.get("time", "").split(" ")[-1] if item.get("time") else ""
                label = f"{item['query'][:28]}{'…' if len(item['query']) > 28 else ''}"
                if st.button(
                    label, key=f"hist_{i}", use_container_width=True,
                    help=f"{intent_label} · {item.get('time', '')} · {item.get('answer_preview', '')[:80]}"
                ):
                    st.session_state._rerun_query = item["query"]
                    st.rerun()
        else:
            st.caption("暂无搜索记录")

    st.divider()

    # ── Upload Document ──
    with st.expander("上传文档 (RAG)", expanded=False):
        uploaded_file = st.file_uploader(
            "选择文档文件",
            type=["md", "txt", "markdown", "py", "js", "ts", "html", "htm",
                  "json", "yaml", "yml", "java", "go", "rs", "sql",
                  "cfg", "ini", "conf", "toml", "xml", "csv", "log",
                  "pdf", "docx", "xlsx", "xls",
                  "png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff", "tif"],
            key="doc_uploader",
            help="支持 PDF / Word / Excel / Markdown / 代码 / 图片，最大 20MB。PDF 逐页分类，图片自动 OCR。",
        )
        if uploaded_file is not None:
            if st.button("上传并索引", use_container_width=True, key="btn_upload_doc"):
                with st.spinner(f"正在处理 {uploaded_file.name} …"):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                        resp = requests.post(f"{API_BASE}/api/upload/document", files=files, timeout=120)
                        if resp.status_code == 200:
                            data = resp.json()
                            st.success(data['message'])
                            st.caption(f"文档 ID: {data['doc_id']}，{data['chunks']} 个文本块")
                        else:
                            detail = resp.json().get("detail", resp.text)
                            st.error(f"上传失败: {detail}")
                    except Exception as e:
                        st.error(f"上传失败: {e}")

    # ── Upload Database ──
    with st.expander("上传数据库 (NL2SQL)", expanded=False):
        uploaded_db = st.file_uploader(
            "选择 SQLite 数据库",
            type=["db", "sqlite", "sqlite3", "db3"],
            key="db_uploader",
            help="上传 .db 或 .sqlite 文件，最大 200MB",
        )
        if uploaded_db is not None:
            if st.button("上传数据库", use_container_width=True, key="btn_upload_db"):
                with st.spinner(f"正在上传 {uploaded_db.name} …"):
                    try:
                        files = {"file": (uploaded_db.name, uploaded_db.getvalue())}
                        resp = requests.post(f"{API_BASE}/api/upload/database", files=files, timeout=120)
                        if resp.status_code == 200:
                            data = resp.json()
                            st.success(data['message'])
                            st.caption(f"表: {', '.join(data['tables'][:8])}")
                            st.session_state.active_db = data["filename"]
                        else:
                            detail = resp.json().get("detail", resp.text)
                            st.error(f"上传失败: {detail}")
                    except Exception as e:
                        st.error(f"上传失败: {e}")

    # ── Knowledge Base Management ──
    with st.expander("知识库管理", expanded=False):
        # Documents
        st.caption("已上传文档")
        if st.button("刷新", key="refresh_docs"):
            st.rerun()
        try:
            resp = requests.get(f"{API_BASE}/api/upload/documents", timeout=10)
            if resp.status_code == 200:
                docs = resp.json()
                if docs:
                    for i, doc in enumerate(docs):
                        c1, c2 = st.columns([5, 1])
                        c1.caption(f"{doc['filename']} ({doc['chunks']} chunks)")
                        if c2.button("×", key=f"del_{i}_{doc['filename'][:10]}", help="删除此文档"):
                            requests.delete(
                                f"{API_BASE}/api/upload/document",
                                params={"filename": doc["filename"]}, timeout=10
                            )
                            st.rerun()
                else:
                    st.caption("(暂无)")
        except Exception:
            st.caption("后端未连接")

        st.divider()

        # Databases
        st.caption("已上传数据库")
        if st.button("刷新", key="refresh_dbs"):
            st.rerun()
        try:
            resp = requests.get(f"{API_BASE}/api/upload/databases", timeout=10)
            if resp.status_code == 200:
                dbs = resp.json()
                if dbs:
                    for i, db in enumerate(dbs):
                        active = db.get("is_active", False)
                        marker = "●" if active else "○"
                        size_kb = db['size_bytes'] / 1024
                        st.caption(f"{marker} {db['filename']} ({size_kb:.0f} KB, {len(db['tables'])} 表)")
                        if not active:
                            if st.button("切换到此库", key=f"switch_{i}"):
                                requests.post(
                                    f"{API_BASE}/api/upload/database/switch",
                                    json={"filename": db["filename"]}, timeout=10
                                )
                                st.rerun()
                else:
                    st.caption("(暂无)")
        except Exception:
            st.caption("后端未连接")

    st.divider()

    # ── Document Ingestion (directory scan) ──
    with st.expander("文档摄入 (目录扫描)", expanded=False):
        ingest_path = st.text_input("文档目录", value="./docs/samples")
        if st.button("开始摄入", use_container_width=True):
            with st.spinner("正在摄入文档 …"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/api/ingest/run",
                        json={"source_type": "local_fs", "path": ingest_path},
                        timeout=120,
                    )
                    data = resp.json()
                    st.success(
                        f"新增 {data['new_documents']} 篇，跳过 {data['skipped_documents']} 篇，"
                        f"共 {data['new_vector_count']} 条向量"
                    )
                    if data["errors"]:
                        st.warning(f"{data['failed_documents']} 篇失败:\n" + "\n".join(data["errors"][:5]))
                except Exception as e:
                    st.error(f"摄入失败: {e}")

    # ── Knowledge Base Stats ──
    st.header("知识库统计")
    if st.button("刷新统计", use_container_width=True):
        try:
            resp = requests.get(f"{API_BASE}/api/ingest/stats", timeout=5)
            d = resp.json()
            st.metric("向量总数", d["total_vectors"])
            st.caption(f"BM25 文档: {d['bm25_documents']}　词汇: {d['bm25_vocabulary']}")
        except Exception:
            st.warning("无法连接后端")

    # ── NL2SQL Status ──
    try:
        resp = requests.get(f"{API_BASE}/api/upload/database/active", timeout=5)
        if resp.status_code == 200:
            active_info = resp.json()
            active_name = active_info.get("active_database")
            if active_name:
                st.caption(f"● NL2SQL 当前库: **{active_name}**")
            else:
                st.caption("○ NL2SQL: 使用默认数据库")
    except Exception:
        pass

    st.divider()

    # ── Mode Help ──
    st.header("双模式说明")
    st.caption("**RAG** 文档类问题\n\"Redis 怎么部署？\"")
    st.caption("**SQL** 数据类问题\n\"总共有多少订单？\"")
    st.caption("系统自动判断模式")


# ═══════════════════════════════════════════════════════════════
#  Main Content — Title
# ═══════════════════════════════════════════════════════════════
st.title("企业知识库问答系统")


# ═══════════════════════════════════════════════════════════════
#  Query runner
# ═══════════════════════════════════════════════════════════════
def _run_query(prompt: str):
    """Execute a query, display the result, and record history."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()

        try:
            resp = requests.post(
                f"{API_BASE}/api/chat/send",
                json={"session_id": st.session_state.session_id, "query": prompt, "top_k": 5},
                timeout=60,
            )
            data = resp.json()

            if data.get("session_id"):
                st.session_state.session_id = data["session_id"]

            answer = data["answer"]
            intent = data.get("intent", "rag")

            placeholder.markdown(answer)

            # NL2SQL expander
            if intent == "sql" and data.get("nl2sql"):
                nl2sql = data["nl2sql"]
                if nl2sql.get("sql"):
                    with st.expander("查看 SQL 与数据"):
                        st.caption(f"SQL: `{nl2sql['sql']}`")
                        st.caption(
                            f"{nl2sql['sql_explanation']} · "
                            f"耗时 {nl2sql['execution_time_ms']:.0f} ms · "
                            f"返回 {nl2sql['row_count']} 行"
                        )
                        if nl2sql.get("columns") and nl2sql.get("rows"):
                            df = pd.DataFrame(nl2sql["rows"], columns=nl2sql["columns"])
                            st.dataframe(df, use_container_width=True)
                            if nl2sql.get("truncated"):
                                st.caption(f"结果已截断，仅展示前 {nl2sql['row_count']} 行")

            # Intent badge
            if intent == "sql":
                st.caption("NL2SQL 数据查询模式")
            else:
                st.caption("RAG 文档检索模式")

            # Save message
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "intent": intent,
                "nl2sql": data.get("nl2sql"),
            })

            # Save search history (dedup)
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


# ═══════════════════════════════════════════════════════════════
#  Chat history display
# ═══════════════════════════════════════════════════════════════
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("intent") == "sql" and msg.get("nl2sql"):
            st.markdown(msg["content"])
            nl2sql = msg["nl2sql"]
            if nl2sql.get("sql"):
                with st.expander("查看 SQL 与数据"):
                    st.caption(f"SQL: `{nl2sql['sql']}`")
                    st.caption(
                        f"{nl2sql['sql_explanation']} · "
                        f"耗时 {nl2sql['execution_time_ms']:.0f} ms"
                    )
                    if nl2sql.get("columns") and nl2sql.get("rows"):
                        df = pd.DataFrame(nl2sql["rows"], columns=nl2sql["columns"])
                        st.dataframe(df, use_container_width=True)
                        if nl2sql.get("truncated"):
                            st.caption(f"结果已截断，仅展示前 {nl2sql['row_count']} 行")
        else:
            st.markdown(msg["content"])


# ═══════════════════════════════════════════════════════════════
#  Input handling
# ═══════════════════════════════════════════════════════════════
if "_rerun_query" in st.session_state and st.session_state._rerun_query:
    prompt = st.session_state._rerun_query
    st.session_state._rerun_query = None
    _run_query(prompt)

if prompt := st.chat_input("输入你的问题，系统自动判断 RAG 或 SQL 模式 …"):
    _run_query(prompt)
