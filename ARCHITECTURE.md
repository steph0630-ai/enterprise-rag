# 架构文档 — Enterprise RAG

## 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit UI (:8501)                     │
│              Chat 界面 + 历史搜索 + 数据表展示                 │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP
┌────────────────────────▼────────────────────────────────────┐
│                  FastAPI (:8000)                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ /health   │  │ /chat/*   │  │ /ingest/* │               │
│  │ /ready    │  │  对话+NL2SQL │  │  文档摄入  │               │
│  └───────────┘  └─────┬─────┘  └─────┬─────┘               │
└────────────────────────┼─────────────┼───────────────────────┘
                         │             │
              ┌──────────┴─────┐       │
              ▼                ▼       ▼
      ┌─────────────┐  ┌────────────┐ ┌──────────┐
      │ Qdrant      │  │ BM25 Index │ │ SQLite   │
      │ 向量检索     │  │ 关键词检索  │ │ NL2SQL   │
      │ :6333       │  │ (内存)      │ │ (只读)    │
      └─────────────┘  └────────────┘ └──────────┘
              │                │
              └──────┬─────────┘
                     ▼
              ┌───────────┐
              │ RRF 融合   │
              │ (排名融合) │
              └─────┬─────┘
                    ▼
              ┌───────────┐
              │ DeepSeek  │
              │ LLM 生成   │
              └───────────┘
```

## 请求链路

### RAG 路径

```
1. QueryRewrite（可选）→ 补全指代、补全上下文
2. Embedding（SiliconFlow bge-m3）→ 向量化
3. Vector Search（Qdrant）→ top-20
4. Keyword Search（BM25）→ top-20
5. RRF Fusion → top-5
6. [可选] LLM Reranker → 精排 top-5
7. Prompt 组装 → LLM 生成 → 引用解析 → 返回
```

### NL2SQL 路径

```
1. Intent Router（LLM 分类）→ sql?
2. Schema Manager → 实时读取 DB 表结构 + 采样数据
3. SQL Generator（LLM）→ 生成 SELECT 语句
4. SQL Validator → EXPLAIN 预检语法
5. SQL Executor → 只读连接执行（超时/行数限制）
6. Answer Formatter（LLM）→ SQL 结果 → 自然语言解释
```

## 核心设计决策

### 1. 为什么混合检索而不是纯向量？

纯向量检索对语义匹配强，但精确关键词（如 "8080端口"、"maxmemory"）会漏。BM25 补上了精确匹配的短板。RRF 融合避免了两路分数不可比的问题。

### 2. 为什么 BM25 自实现而不是用 Elasticsearch？

MVP 阶段减少外部依赖，Qdrant 向量检索 + 内存 BM25 足够。50 篇文档 BM25 内存占用 < 10MB。生产环境可切换到 ES + Qdrant 双引擎。

### 3. 为什么 NL2SQL 用 LLM 生成而非模板匹配？

模板匹配无法处理灵活的自然语言表达（"卖得最好的那个" = ORDER BY DESC LIMIT 1）。LLM 生成 SQL 能覆盖绝大多数查询模式。安全措施（只读+超时+正则拦截）防止 SQL 注入。

### 4. 为什么用 DeepSeek 而不是 Claude/GPT？

- 成本差 10-20 倍，开发调试不心疼
- 中文能力强，企业文档是中文
- API 兼容 OpenAI 格式，迁移零成本

### 5. 为什么 Embedding 用 bge-m3？

- 中文 Embedding 目前效果最好的开源模型
- 支持 1024 维向量，精度和速度平衡
- SiliconFlow 免费额度够开发用

## 模块职责

| 模块 | 职责 | 关键设计 |
|---|---|---|
| `app/core/llm.py` | LLM 调用封装 | 3 次重试 + 指数退避 + Token 日志 |
| `app/retrieval/hybrid_retriever.py` | 混合检索编排 | 双路召回 → RRF 融合 |
| `app/nl2sql/sql_executor.py` | SQL 安全执行 | 只允许 SELECT + 只读连接 + 超时 + 行数限制 |
| `app/nl2sql/sql_generator.py` | SQL 生成 | 三重容错解析（JSON → Markdown → 正则） |
| `app/chat/session.py` | 会话管理 | TTL 过期 + 上下文摘要压缩 |
| `eval/metrics.py` | 评测指标 | Recall/Faithfulness/SQL Accuracy 多维度 |

## 数据流

### 文档摄入

```
文件系统 → Parser (Markdown/PDF) → Chunker (递归字符)
→ Embedding (bge-m3) → Qdrant (向量)
→ BM25 Index (关键词)
→ 幂等检查 (基于 content hash)
```

### 数据库 (NL2SQL)

Brazilian E-Commerce (Kaggle 公开数据)：
- 8 张表、55 万行
- orders (99k) → order_items (112k) → products (33k)
- customers (99k)、sellers (3k)、reviews (99k)
- 支持多表 JOIN、GROUP BY、时间聚合、子查询

## 安全措施

| 层 | 措施 |
|---|---|
| SQL 生成 | LLM Prompt 约束 + 正则拦截 DROP/DELETE/INSERT/UPDATE/ALTER |
| SQL 执行 | SQLite 只读模式 + 10秒超时 + 200行截断 + EXPLAIN 预检 |
| API | CORS 域名白名单 (不再用 *) |
| 密钥 | .env + .gitignore 防护 |

## 测试策略

```
47 个单元测试覆盖:
├── schema_manager (6)  — DB 结构读取
├── sql_executor (10)   — SQL 安全拦截 + 边界情况
├── chunker (7)         — 分块策略 + 重叠
├── session (10)        — 会话生命周期
├── eval (12)           — 数据集 + 指标
├── chat_api (8)        — API 响应结构
└── nl2sql_integration (9) — 端到端 (需 API)

评测数据集: 14 条标注样本 (7 RAG + 7 NL2SQL)
```

## 已知限制与改进方向

| 限制 | 改进方案 |
|---|---|
| BM25 索引在内存中，重启丢失 | 持久化到磁盘或从 Qdrant payload 重建 |
| 会话存储在内存中 | 切换到 Redis |
| 没有 API 限流 | 添加 slowapi / token bucket |
| 流式接口不支持 NL2SQL | 将 NL2SQL 结果分段流式输出 |
| Reranker 增加延迟 | 做成可选项，UI 开关控制 |
