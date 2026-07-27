# Enterprise RAG — 企业知识库智能问答系统

**RAG + NL2SQL 双模式**，支持文档检索和数据查询，自动路由。

## 快速开始

```bash
# 1. 配置
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 EMBEDDING_API_KEY

# 2. 启动 Qdrant
docker compose up -d qdrant

# 3. 一键启动
bash scripts/start.sh

# 或手动分别启动:
uvicorn app.main:app --host 0.0.0.0 --port 8000    # 后端
streamlit run ui/app.py --server.port 8501           # 前端
```

启动后访问 http://localhost:8501。

## 核心功能

| 功能 | 说明 |
|---|---|
| 📚 **RAG 文档问答** | 多源文档摄入 → 混合检索 → LLM 生成带引用回答 |
| 🤖 **NL2SQL 数据查询** | 自然语言 → SQL → 安全执行 → 自然语言解释 |
| 🧠 **意图自动路由** | LLM 判断问题类型，自动分发到 RAG 或 NL2SQL |
| 🔍 **混合检索** | Dense(向量) + Sparse(BM25) + RRF 融合 |
| 💬 **多轮对话** | 查询改写 + 会话管理 + 上下文压缩 |
| 📊 **评测体系** | 14 条标注样本 + 多维度指标 + CI 集成 |
| 🛡 **SQL 安全** | 只允许 SELECT + 超时 kill + 行数截断 + 正则拦截 |

## 架构

```
用户提问
    │
    ▼
┌──────────────┐
│ Intent Router │──→ rag: 混合检索 → Qdrant + BM25 → RRF → LLM 生成
│  (LLM 分类)   │
└──────────────┘──→ sql: Schema → LLM 生成 SQL → SQLite 只读执行 → 自然语言解释
```

详见 `ARCHITECTURE.md`。

## 项目结构

```
enterprise-rag/
├── app/
│   ├── main.py                    # FastAPI 入口 + 健康检查
│   ├── config.py                  # 配置管理 (pydantic-settings)
│   ├── api/
│   │   ├── chat.py                # 对话 API (意图路由 + RAG + NL2SQL)
│   │   └── ingest.py              # 文档摄入 API
│   ├── core/
│   │   ├── llm.py                 # LLM 封装 (重试 + Token 日志)
│   │   ├── embedding.py           # Embedding 服务 (bge-m3)
│   │   ├── chunker.py             # 递归字符分块
│   │   └── parser.py              # 文档解析 (Markdown/PDF)
│   ├── ingestion/
│   │   ├── pipeline.py            # 摄入流程编排
│   │   └── connectors/            # 数据源连接器 (local_fs + 可扩展)
│   ├── retrieval/
│   │   ├── vector_store.py        # Qdrant 封装
│   │   ├── keyword_search.py      # BM25 关键词检索
│   │   ├── hybrid_retriever.py    # 混合检索 + RRF 融合
│   │   └── reranker.py            # LLM Reranker 精排
│   ├── generation/
│   │   ├── generator.py           # RAG 答案生成 + 引用解析
│   │   └── prompts.py             # Prompt 模板管理
│   ├── chat/
│   │   ├── session.py             # 会话管理 (TTL + 上下文摘要)
│   │   └── query_rewriter.py      # 多轮对话查询改写
│   └── nl2sql/
│       ├── intent_router.py       # 意图分类器
│       ├── schema_manager.py      # DB Schema 管理
│       ├── sql_generator.py       # LLM 生成 SQL (三重容错)
│       ├── sql_executor.py        # SQL 安全执行器
│       └── pipeline.py            # NL2SQL 全链路编排
├── eval/
│   ├── dataset.py                 # 14 条标注评测样本
│   ├── metrics.py                 # 多维度指标计算
│   └── runner.py                  # 评测运行器 (--ci 模式)
├── tests/                         # 47 个单元 + 集成测试
├── docs/samples/                  # 50 篇企业文档
├── data/
│   ├── business.db                # 巴西电商数据集 (8表 55万行)
│   ├── seed_data.py               # 小型示例数据种子
│   └── import_olist.py            # Brazilian E-Commerce 导入脚本
├── scripts/
│   ├── start.sh                   # 一键启动脚本
│   └── generate_docs.py           # 批量文档生成器
├── ui/app.py                      # Streamlit Chat 界面
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## 测试

```bash
# 全部单元测试
pytest tests/ -v

# 跳过需要外部服务的测试
pytest tests/ -v -k "not (NL2SQLPipeline or TestChatAPI)"

# 评测运行器
python eval/runner.py --ci --output report.md
```

## 技术栈

| 组件 | 选型 |
|---|---|
| LLM | DeepSeek (OpenAI 兼容) |
| Embedding | bge-m3 (SiliconFlow) |
| 向量库 | Qdrant |
| 关键词检索 | BM25 (自实现) |
| 数据库 (NL2SQL) | SQLite (Brazilian E-Commerce) |
| 后端 | FastAPI |
| 前端 | Streamlit |
| 部署 | Docker Compose |

## 数据

- **知识库**: 50 篇企业文档 (运维手册/技术规范/管理制度/故障复盘/产品文档)
- **数据库**: [Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) — 9.9万订单、11万订单明细、10万客户、10万评价
