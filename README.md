# WA7ER RAG

## Product Preview

### Login

![Login screen](docs/images/login-screen.png)

### Chat Workspace — Empty State

![Chat workspace before conversation](docs/images/chat-empty-screen.png)

### Chat Workspace — Conversation

![Chat workspace with RAG response](docs/images/chat-conversation-screen.png)


面向企业内部技术文档的生产型 Retrieval-Augmented Generation（RAG）系统。项目覆盖文档治理、清洗、双格式导出、语义增强、向量入库、多路召回、父文档扩展、模型精排、答案生成、引用追踪、多租户安全、反馈闭环、离线评测和容器化部署。

本项目不依赖 LangChain 或 LlamaIndex 等通用 RAG 编排框架，核心链路使用可替换的接口和轻量服务层实现，便于控制每个数据处理阶段、定位检索问题并按实际业务需求调整策略。

> 本仓库不包含任何真实 API Key、数据库密码、用户数据或本地运行产物。所有敏感配置均通过项目根目录下未纳入 Git 的 `.env` 文件加载。

## 目录

- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [RAG 处理流程](#rag-处理流程)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [运行模式](#运行模式)
- [环境变量](#环境变量)
- [数据库与基础设施](#数据库与基础设施)
- [初始化管理员](#初始化管理员)
- [文档入库](#文档入库)
- [问答接口](#问答接口)
- [主要 API](#主要-api)
- [离线评测](#离线评测)
- [数据治理](#数据治理)
- [监控](#监控)
- [测试](#测试)
- [Docker 部署](#docker-部署)
- [Kubernetes 部署](#kubernetes-部署)
- [安全说明](#安全说明)
- [当前边界](#当前边界)
- [开发约定](#开发约定)

## 核心能力

### 数据处理

- 支持 PDF、DOCX、Markdown、HTML 和纯文本文件。
- 提取 DOCX 内嵌图片及 PDF 页面图片资源。
- 使用可扩展正则规则清理页面元信息、论坛结构标记、时间戳、纯数字噪音和兼容性提示。
- 每份文档同时输出：
  - 适合机器入库的干净 Markdown。
  - 适合用户查看和引用的 Word 文档。
- 记录清洗规则命中次数、文本长度和处理状态。
- 使用校验和与检查点跳过未变化文档，支持强制重新处理。

### 元数据增强

每份文档可生成以下语义元数据：

- 一句话摘要。
- 关键技术术语。
- 文档能够回答的问题列表。

元数据可由启发式实现生成，也可以通过 OpenAI 兼容模型网关生成。问题型元数据可提升用户自然语言问题与文档内容之间的匹配能力。

### 分块策略

- 不超过 `RAG_SHORT_DOCUMENT_LIMIT` 的短文档保持整篇入库，避免破坏完整语义。
- 长文档使用递归字符切分。
- 默认参数：
  - Chunk Size：`6000`
  - Chunk Overlap：`500`
- 每个 Chunk 的 Embedding 文本附带标题、摘要、关键词和可回答问题。
- 原始正文与 Embedding 文本分离，避免增强信息污染最终引用内容。

### 检索与生成

- Query Rewrite：将多轮指代问题改写为自包含问题。
- HyDE：生成假设答案作为额外检索查询。
- 原问题、改写问题和 HyDE 查询多路向量召回。
- 使用 Reciprocal Rank Fusion（RRF）融合多路检索结果。
- 父文档扩展：任意 Chunk 命中后，拉取该文档全部 Chunk 并按 `chunk_index` 重组。
- Milvus HNSW 向量索引与 Embedding 维度校验。
- 支持词法 Rerank 和外部 HTTP Rerank 服务。
- 默认粗排候选数 `20`，最终上下文数 `5`。
- 普通闲聊可绕过知识库，直接调用生成模型。
- 返回改写查询、引用文档、相关度分数和各阶段耗时。

### 业务与安全

- PostgreSQL 持久化消息、检索轨迹、反馈、用户、租户、API Key 和审计事件。
- Redis 存储多轮会话、答案缓存、滑动窗口限流和分布式锁。
- JWT 登录和 API Key 鉴权。
- 多租户数据隔离。
- 基于角色和权限的接口控制。
- 点赞、点踩及反馈理由记录。
- 请求审计、Request ID 和 Prometheus 指标。

### 前端

- Next.js 单页应用。
- 租户、用户名和密码登录。
- 文档上传与入库状态展示。
- 多轮问答和 Session ID 复用。
- 改写查询展示。
- Markdown 文本、代码、链接和图片渲染。
- 引用文档跳转。
- 点赞和点踩反馈。

## 系统架构

```mermaid
flowchart LR
    U["Browser / API Client"] --> W["Next.js Web"]
    W --> A["FastAPI"]

    A --> SEC["Security Service"]
    SEC --> PG[(PostgreSQL)]
    SEC --> RD[(Redis)]

    A --> ING["Ingestion Service"]
    ING --> PARSE["Parser + Cleaner"]
    PARSE --> META["Metadata Enrichment"]
    META --> CHUNK["Chunking"]
    CHUNK --> EMB["Embedding API"]
    EMB --> MV[(Milvus)]
    ING --> OBJ["Local / MinIO Object Store"]

    A --> RAG["RAG Service"]
    RAG --> RW["Query Rewrite"]
    RAG --> HYDE["HyDE"]
    RW --> MV
    HYDE --> MV
    MV --> PARENT["Parent Document Expansion"]
    PARENT --> RR["Rerank Service"]
    RR --> LLM["Generation Model"]
    LLM --> A

    RAG --> PG
    RAG --> RD
    A --> PROM["Prometheus Metrics"]
```

## RAG 处理流程

### 入库链路

```text
原始文件
  → 格式解析
  → 噪音清洗
  → 图片提取
  → Markdown / Word 双版本导出
  → 摘要、关键词、Questions 元数据增强
  → 短文整篇或长文递归分块
  → Embedding
  → Milvus 向量与标量字段入库
  → 保存检查点
```

### 查询链路

```text
用户问题 + 会话历史
  → 判断是否需要知识库检索
  → Query Rewrite
  → HyDE 假设答案
  → 多路向量召回
  → RRF 融合
  → 根据命中 Chunk 拉取完整父文档
  → Top-20 Rerank
  → Top-5 上下文
  → LLM 生成答案和引用
  → PostgreSQL 保存检索轨迹
  → Redis 保存会话与缓存
```

### 普通对话路由

问候、感谢和简单闲聊不会强制查询知识库。系统直接调用生成模型，避免在用户输入“你好”时返回“未找到相关信息”。专业问题或知识型问题进入完整 RAG 链路。

## 技术栈

| 层级 | 技术 |
|---|---|
| API | Python 3.11、FastAPI、Pydantic |
| Web | Next.js、React、TypeScript |
| 关系数据库 | PostgreSQL、SQLAlchemy Async、asyncpg |
| 状态存储 | Redis |
| 向量数据库 | Milvus |
| 对象存储 | 本地签名文件服务或 MinIO |
| 模型协议 | OpenAI Compatible API |
| 精排 | 词法 Rerank 或 HTTP Rerank API |
| 文档处理 | python-docx、pypdf、BeautifulSoup、markdownify |
| 监控 | Prometheus、Grafana 配置示例 |
| 部署 | Docker Compose、Kubernetes |
| 测试 | pytest、pytest-asyncio、Ruff |

## 项目结构

```text
.
├─ apps/
│  ├─ api/                    # FastAPI 应用、路由、Schema、依赖注入
│  └─ web/                    # Next.js 前端
├─ packages/rag_core/src/
│  └─ rag_core/
│     ├─ cleaning/            # 解析、清洗、双格式导出
│     ├─ enrichment/          # 摘要、关键词、Questions 增强
│     ├─ generation/          # LLM 生成与图片 URL 替换
│     ├─ governance/          # 数据盘点、抽样、审核、版本比较
│     ├─ infrastructure/      # PostgreSQL、Redis、Milvus、MinIO、Rerank
│     ├─ ingestion/           # 分块与 Embedding
│     ├─ retrieval/           # Rewrite、HyDE、RRF、父文档召回、Rerank
│     ├─ config.py            # 环境配置
│     ├─ contracts.py         # 组件协议
│     ├─ models.py            # 领域模型
│     ├─ security_service.py  # 多租户安全服务
│     └─ services.py          # 入库与 RAG 编排服务
├─ configs/                   # 清洗与 RAG 配置示例
├─ deploy/
│  ├─ docker/                 # Dockerfile 与 Compose
│  ├─ kubernetes/             # K8s 工作负载示例
│  └─ monitoring/             # Prometheus 配置
├─ evaluation/                # Recall@K / MRR 评测
├─ migrations/                # PostgreSQL 初始化 SQL
├─ pipelines/                 # 离线入库与数据治理 CLI
├─ scripts/                   # Windows 辅助脚本
├─ tests/                     # 单元测试和集成测试
├─ .env.example               # 无敏感信息的配置模板
└─ pyproject.toml
```

## 快速开始

### 前置要求

- Python `3.11`
- Node.js `20+`，推荐 `22`
- npm
- 可选：Conda
- 生产组件模式还需要：
  - PostgreSQL
  - Redis
  - Milvus
  - MinIO 或共享文件存储
  - OpenAI 兼容模型 API
  - 可选的 Rerank API

### 1. 克隆项目

```bash
git clone <repository-url>
cd <repository-directory>
```

### 2. 创建 Python 环境

使用 Conda：

```bash
conda create -n RAG_E python=3.11 -y
conda activate RAG_E
```

或使用 venv：

```bash
python -m venv .venv
```

Windows：

```bat
.venv\Scripts\activate
```

Linux/macOS：

```bash
source .venv/bin/activate
```

### 3. 安装后端依赖

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 4. 安装前端依赖

```bash
cd apps/web
npm install
cd ../..
```

### 5. 创建本地配置

Windows：

```bat
copy .env.example .env
```

Linux/macOS：

```bash
cp .env.example .env
```

不要把 `.env` 提交到 Git。请至少替换以下配置：

```env
SECURITY_JWT_SECRET=replace-with-a-long-random-secret
SECURITY_BOOTSTRAP_TOKEN=replace-with-a-one-time-bootstrap-token
SECURITY_ASSET_SIGNING_SECRET=replace-with-another-random-secret
```

### 6. Mock 模式启动

Mock 模式无需 PostgreSQL、Redis、Milvus、MinIO 或外部模型服务，适合快速体验和开发测试：

```env
RAG_USE_MOCKS=true
RAG_METADATA_PROVIDER=auto
RAG_EMBEDDING_PROVIDER=auto
RAG_VECTOR_STORE_PROVIDER=auto
RAG_OBJECT_STORE_PROVIDER=auto
RAG_REWRITE_PROVIDER=auto
RAG_HYDE_PROVIDER=auto
RAG_RERANK_PROVIDER=auto
RAG_GENERATION_PROVIDER=auto
RAG_TRACE_PROVIDER=auto
RAG_SECURITY_PROVIDER=auto
RAG_STATE_PROVIDER=auto
```

启动 API：

```bash
set PYTHONPATH=packages\rag_core\src;apps\api
python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --reload
```

PowerShell：

```powershell
$env:PYTHONPATH="packages\rag_core\src;apps\api"
python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --reload
```

Linux/macOS：

```bash
PYTHONPATH=packages/rag_core/src:apps/api \
python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --reload
```

启动 Web：

```bash
cd apps/web
npm run dev
```

访问：

- Web：`http://localhost:3000`
- API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/api/v1/health`
- Prometheus 指标：`http://localhost:8000/api/v1/metrics`

Windows 用户也可以在激活 Python 环境后运行：

```bat
scripts\run_api.cmd
scripts\run_web.cmd
```

### Windows 一键启停

当前本地生产配置可以通过以下脚本统一管理 PostgreSQL 检查、Redis、Milvus、Attu、API 和 Web：

```bat
scripts\start_all.cmd
```

停止项目服务：

```bat
scripts\stop_all.cmd
```

启动脚本使用固定端口：Web `3000`、API `8000`、Attu `8001`、Milvus `19530`。日志写入 `tmp\runtime\logs`。停止脚本不会关闭 PostgreSQL，避免影响其他数据库。

## 运行模式

项目支持两种配置方式。

### 总体 Mock 开关

```env
RAG_USE_MOCKS=true
```

当各组件 Provider 为 `auto` 时：

| 组件 | Mock 默认 | Production 默认 |
|---|---|---|
| Metadata | heuristic | openai |
| Embedding | deterministic | openai |
| Vector Store | memory | milvus |
| Object Store | local | minio |
| Rewrite | heuristic | openai |
| HyDE | heuristic | openai |
| Rerank | lexical | http |
| Generation | extractive | openai |
| Trace | memory | postgres |
| Security | memory | postgres |
| State | memory | redis |

### 独立 Provider 覆盖

即使 `RAG_USE_MOCKS=true`，也可以按组件逐步接入真实基础设施：

```env
RAG_USE_MOCKS=true
RAG_EMBEDDING_PROVIDER=openai
RAG_VECTOR_STORE_PROVIDER=milvus
RAG_GENERATION_PROVIDER=openai
RAG_TRACE_PROVIDER=postgres
RAG_SECURITY_PROVIDER=postgres
RAG_STATE_PROVIDER=redis
RAG_RERANK_PROVIDER=http
RAG_OBJECT_STORE_PROVIDER=local
```

这种模式适合开发环境逐项联调。

## 环境变量

完整模板见 `.env.example`。

### 应用与安全

| 变量 | 说明 |
|---|---|
| `APP_NAME` | 应用名称 |
| `APP_ENV` | 环境名称 |
| `APP_DEBUG` | 调试开关 |
| `LOG_LEVEL` | 日志等级 |
| `SECURITY_ENABLED` | 是否启用安全模块 |
| `SECURITY_JWT_SECRET` | JWT 签名密钥，生产必须更换 |
| `SECURITY_JWT_ISSUER` | JWT Issuer |
| `SECURITY_JWT_AUDIENCE` | JWT Audience |
| `SECURITY_ACCESS_TOKEN_TTL_SECONDS` | Access Token 有效期 |
| `SECURITY_BOOTSTRAP_TOKEN` | 首次管理员初始化令牌 |
| `SECURITY_ASSET_SIGNING_SECRET` | 本地文件 URL 签名密钥 |

### Provider

| 变量 | 可选值 |
|---|---|
| `RAG_METADATA_PROVIDER` | `auto` / `heuristic` / `openai` |
| `RAG_EMBEDDING_PROVIDER` | `auto` / `deterministic` / `openai` |
| `RAG_VECTOR_STORE_PROVIDER` | `auto` / `memory` / `milvus` |
| `RAG_OBJECT_STORE_PROVIDER` | `auto` / `local` / `minio` |
| `RAG_REWRITE_PROVIDER` | `auto` / `heuristic` / `openai` |
| `RAG_HYDE_PROVIDER` | `auto` / `heuristic` / `openai` |
| `RAG_RERANK_PROVIDER` | `auto` / `lexical` / `http` |
| `RAG_GENERATION_PROVIDER` | `auto` / `extractive` / `openai` |
| `RAG_TRACE_PROVIDER` | `auto` / `memory` / `postgres` |
| `RAG_SECURITY_PROVIDER` | `auto` / `memory` / `postgres` |
| `RAG_STATE_PROVIDER` | `auto` / `memory` / `redis` |

### 模型配置

```env
MODEL_GATEWAY_BASE_URL=https://model-gateway.example.com/v1
MODEL_GATEWAY_API_KEY=replace-with-model-api-key

RAG_EMBEDDING_MODEL=your-embedding-model
RAG_EMBEDDING_DIMENSION=1024
RAG_GENERATION_MODEL=your-chat-model
RAG_REWRITE_MODEL=your-lightweight-chat-model
RAG_HYDE_MODEL=your-lightweight-chat-model
```

模型网关需要兼容 OpenAI 风格接口。Embedding 维度一旦用于创建 Milvus Collection，不应直接修改；更换维度时应创建新 Collection 并重新入库。

### Rerank 配置

```env
RAG_RERANK_PROVIDER=http
RAG_RERANK_MODEL=your-rerank-model
RERANK_ENDPOINT=https://rerank-provider.example.com/v1/rerank
RERANK_API_KEY=replace-with-rerank-api-key
RERANK_TIMEOUT_SECONDS=10
RERANK_MAX_RETRIES=2
RERANK_RETRY_BASE_DELAY_SECONDS=0.25
RERANK_RETRY_MAX_DELAY_SECONDS=2
RERANK_MAX_CONCURRENCY=8
RERANK_QUEUE_TIMEOUT_SECONDS=2
RERANK_CIRCUIT_FAILURE_THRESHOLD=5
RERANK_CIRCUIT_RECOVERY_SECONDS=30
RERANK_MAX_DOCUMENT_CHARS=12000
RERANK_FALLBACK_PROVIDER=lexical
```

HTTP Rerank 服务需要接受：

```json
{
  "model": "your-rerank-model",
  "query": "用户问题",
  "documents": ["候选文档一", "候选文档二"],
  "top_n": 2,
  "return_documents": false
}
```

工程化客户端具备以下保护：

- 复用 HTTP 连接池，避免每次请求重新建立连接。
- 使用信号量限制并发请求数。
- 排队超过 `RERANK_QUEUE_TIMEOUT_SECONDS` 时直接降级。
- 对网络异常、超时、`408/425/429/5xx` 执行指数退避重试。
- 优先遵循服务端 `Retry-After`。
- 连续失败达到阈值后开启熔断器。
- 熔断恢复窗口结束后只允许单个 Half-Open 探测请求。
- 服务不可用、响应格式错误或熔断开启时降级到词法精排。
- 截断过长候选文档，控制请求大小和远端推理成本。
- 将远端或降级来源、模型名称和降级原因写入检索轨迹。
- 暴露调用结果、重试、降级、熔断状态、延迟和候选数量指标。

将 `RERANK_FALLBACK_PROVIDER` 设置为 `none` 可以关闭降级，此时远端精排失败会向上抛出错误。生产环境推荐保持 `lexical`。

并返回类似：

```json
{
  "results": [
    {"index": 1, "relevance_score": 0.95},
    {"index": 0, "relevance_score": 0.12}
  ]
}
```

### 检索参数

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `RAG_SHORT_DOCUMENT_LIMIT` | `6000` | 短文档整篇入库阈值 |
| `RAG_CHUNK_SIZE` | `6000` | 长文档 Chunk 大小 |
| `RAG_CHUNK_OVERLAP` | `500` | Chunk 重叠长度 |
| `RAG_VECTOR_TOP_K` | `20` | 每路向量召回数量 |
| `RAG_RERANK_CANDIDATE_COUNT` | `20` | Rerank 候选数量 |
| `RAG_FINAL_TOP_K` | `5` | 最终生成上下文数量 |
| `RAG_HYDE_ENABLED` | `true` | 是否启用 HyDE |
| `RAG_HNSW_M` | `16` | HNSW M |
| `RAG_HNSW_EF_CONSTRUCTION` | `256` | HNSW 构建参数 |
| `RAG_HNSW_EF_SEARCH` | `64` | HNSW 查询参数 |

## 数据库与基础设施

### PostgreSQL

```env
POSTGRES_DSN=postgresql+asyncpg://rag_user:strong-password@localhost:5432/enterprise_rag
```

应用启动时会调用 Repository 的 Schema 初始化逻辑。生产环境建议使用 `migrations/` 下的 SQL，通过正式迁移流程执行。

主要表：

- `tenants`
- `users`
- `tenant_memberships`
- `api_keys`
- `audit_events`
- `messages`
- `feedback`

不要使用 PostgreSQL 超级用户作为应用账号。建议为项目创建独立数据库和最小权限 Owner。

### Redis

```env
RAG_STATE_PROVIDER=redis
REDIS_URL=redis://localhost:6379/0
```

Redis 用于：

- 会话历史及 TTL。
- 查询答案缓存。
- 登录、聊天和上传接口限流。
- 文档入库分布式锁。

应用启动时会执行 Redis Ping，连接失败会阻止 API 启动。

### Milvus

启动本项目提供的 Milvus Standalone：

```bash
docker compose -p enterprise-rag-milvus \
  -f deploy/docker/docker-compose.milvus.yml up -d
```

Windows：

```bat
scripts\start_milvus.cmd
```

配置：

```env
RAG_VECTOR_STORE_PROVIDER=milvus
MILVUS_URI=http://localhost:19530
MILVUS_COLLECTION=enterprise_knowledge_v1
RAG_EMBEDDING_DIMENSION=1024
```

Collection 包含向量字段和用于父文档召回的标量字段。系统会校验 Collection 向量维度，避免不同 Embedding 模型产生的向量混入同一 Collection。

### MinIO

```env
RAG_OBJECT_STORE_PROVIDER=minio
MINIO_ENDPOINT=localhost:9001
MINIO_ACCESS_KEY=replace-with-access-key
MINIO_SECRET_KEY=replace-with-secret-key
MINIO_BUCKET=rag-assets
MINIO_SECURE=false
```

如暂未部署 MinIO，可使用：

```env
RAG_OBJECT_STORE_PROVIDER=local
```

本地对象存储会生成带 HMAC 签名的文件访问地址。多副本生产部署应使用 MinIO 或共享持久卷，不应依赖每个容器的独立本地磁盘。

## 初始化管理员

系统只允许执行一次 Bootstrap。请求头中的 Token 必须与 `.env` 中的 `SECURITY_BOOTSTRAP_TOKEN` 一致。

```bash
curl -X POST http://localhost:8000/api/v1/security/bootstrap \
  -H "Content-Type: application/json" \
  -H "x-bootstrap-token: replace-with-bootstrap-token" \
  -d '{
    "username": "admin",
    "password": "replace-with-a-strong-password",
    "tenant_name": "Default Tenant",
    "tenant_slug": "default"
  }'
```

密码至少 12 个字符。Bootstrap 成功后应轮换或停用 Bootstrap Token。

登录：

```bash
curl -X POST http://localhost:8000/api/v1/security/token \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "replace-with-a-strong-password",
    "tenant_slug": "default"
  }'
```

响应中的 `access_token` 用于后续请求：

```text
Authorization: Bearer <access_token>
```

## 文档入库

### 支持格式

- `.pdf`
- `.docx`
- `.md`
- `.markdown`
- `.html`
- `.htm`
- `.txt`

### API 上传

```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload?force=false" \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@./example.pdf"
```

返回示例：

```json
{
  "document_id": "document-id",
  "filename": "example.pdf",
  "chunk_count": 3,
  "skipped": false,
  "output_markdown": "data/processed/.../example.md",
  "output_docx": "data/processed/.../example.docx",
  "source_url": "http://localhost:8000/api/v1/assets/...",
  "markdown_url": "http://localhost:8000/api/v1/assets/..."
}
```

### CLI 入库

```bash
set PYTHONPATH=packages\rag_core\src;apps\api
python pipelines/ingest.py data/raw
```

强制重新处理：

```bash
python pipelines/ingest.py data/raw --force
```

Windows 辅助脚本：

```bat
scripts\ingest.cmd data\raw
```

## 问答接口

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何配置 MQTT？",
    "session_id": null,
    "history": []
  }'
```

响应示例：

```json
{
  "message_id": "message-id",
  "session_id": "session-id",
  "answer": "回答内容",
  "rewritten_query": "MQTT 如何配置？",
  "citations": [
    {
      "document_id": "document-id",
      "filename": "MQTT配置说明.docx",
      "score": 0.93,
      "source_url": "http://localhost:8000/api/v1/assets/..."
    }
  ],
  "timings_ms": {
    "rewrite": 100.0,
    "hyde_generation": 200.0,
    "retrieval_rerank": 300.0,
    "generation": 500.0,
    "total": 1100.0
  }
}
```

继续多轮对话时传回相同的 `session_id`。如果未显式提供 `history`，系统会从 Redis 或内存 Session Store 读取历史消息。

## 主要 API

所有业务接口前缀为 `/api/v1`。

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 应用健康检查 |
| `GET` | `/metrics` | Prometheus 指标 |
| `POST` | `/security/bootstrap` | 初始化首个管理员和租户 |
| `POST` | `/security/token` | 用户名密码登录 |
| `GET` | `/security/me` | 当前身份与权限 |
| `POST` | `/security/users` | 创建租户用户 |
| `POST` | `/security/api-keys` | 创建 API Key |
| `DELETE` | `/security/api-keys/{key_id}` | 吊销 API Key |
| `GET` | `/security/audit-events` | 查询安全审计事件 |
| `POST` | `/documents/upload` | 上传并入库单个文档 |
| `POST` | `/documents/ingest-directory` | 入库租户原始目录 |
| `GET` | `/documents/stats` | 查询租户向量数量 |
| `POST` | `/chat` | 执行对话或 RAG 问答 |
| `GET` | `/chat/sessions/{session_id}` | 查询会话历史 |
| `DELETE` | `/chat/sessions/{session_id}` | 清除会话历史 |
| `POST` | `/messages/{message_id}/feedback` | 提交点赞、点踩和理由 |
| `POST` | `/governance/audits` | 执行数据质量审计 |
| `GET` | `/governance/audits` | 查询审计任务 |
| `GET` | `/governance/audits/{run_id}` | 查询审计详情 |
| `POST` | `/governance/audits/{run_id}/reviews` | 导入人工审核结果 |
| `POST` | `/governance/comparisons` | 比较两次治理结果 |

完整请求和响应 Schema 请以运行时 Swagger 文档为准：`http://localhost:8000/docs`。

## 离线评测

评测数据格式：

```json
[
  {
    "question": "MQTT 默认端口是多少？",
    "expected_document": "MQTT配置说明.docx"
  }
]
```

运行：

```bash
set PYTHONPATH=packages\rag_core\src;apps\api
python evaluation/evaluate.py evaluation/dataset.example.json
```

Windows：

```bat
scripts\evaluate.cmd evaluation\dataset.example.json
```

输出指标：

- Recall@1
- Recall@5
- Recall@10
- Recall@20
- MRR

生产评测集应来自真实业务问题，并由人工标注正确来源文档。建议分别评估 Rewrite、HyDE、父文档扩展和 Rerank 的增益。

## 数据治理

执行目录盘点、抽样和清洗审计：

```bash
set PYTHONPATH=packages\rag_core\src;apps\api
python pipelines/governance.py audit ./data/raw --sample-size 50 --seed 2026
```

导入人工审核结果：

```bash
python pipelines/governance.py import-review <run-id> ./review.csv
```

比较两次治理结果：

```bash
python pipelines/governance.py compare <baseline-run-id> <current-run-id>
```

治理产物默认写入 `data/reports/`，该目录中的运行结果不会提交到 Git。

## 监控

Prometheus 指标接口：

```text
GET /api/v1/metrics
```

项目已记录或预留以下指标：

- 文档入库成功、失败和跳过数量。
- 清洗、增强、Embedding、检索、Rerank 和生成阶段耗时。
- 用户反馈数量。
- API 请求耗时和状态。

Prometheus 配置示例位于：

```text
deploy/monitoring/prometheus.yml
```

生产环境建议补充：

- API P95 / P99 延迟。
- Milvus 查询耗时与内存使用。
- Redis 命中率和连接状态。
- PostgreSQL 连接池状态。
- Rerank 远端成功、失败、重试、降级、排队超时和熔断状态。
- Rerank 远端与降级延迟以及候选数量分布。
- 模型 Token 消耗。
- 无召回率、点踩率和 Bad Case 数量。

## 测试

运行全部后端检查：

```bash
python -m ruff check packages apps tests
python -m pytest -q
```

Windows：

```bat
scripts\test.cmd
```

前端生产构建：

```bash
cd apps/web
npm run build
```

测试覆盖：

- 清洗规则和双格式处理。
- PDF 解析。
- 短文与长文分块。
- 父文档扩展召回。
- Rerank 候选数量和 HTTP 响应映射。
- HyDE。
- Redis 风格会话、限流和分布式锁逻辑。
- 多租户隔离。
- 用户、角色、JWT、API Key 和审计。
- FastAPI 会话、限流、治理与完整 RAG 流程。

## Docker 部署

### 基础服务与应用

```bash
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

该 Compose 包含：

- PostgreSQL
- Redis
- MinIO
- FastAPI
- Next.js

Milvus 使用独立 Compose 启动：

```bash
docker compose -p enterprise-rag-milvus \
  -f deploy/docker/docker-compose.milvus.yml up -d
```

容器环境下请将 `.env` 中的连接地址改为 Compose Service 名称，例如：

```env
POSTGRES_DSN=postgresql+asyncpg://rag:strong-password@postgres:5432/rag
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
MILVUS_URI=http://milvus-standalone:19530
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

注意：两个独立 Compose 默认不一定处于同一个 Docker Network。生产使用时应合并编排文件或显式配置共享网络。

## Kubernetes 部署

示例清单位于 `deploy/kubernetes/`：

- `api.yaml`：FastAPI 三副本。
- `web.yaml`：Next.js 两副本。
- `reranker.yaml`：GPU Rerank 工作负载示例。

部署前需要自行创建：

- `rag-config` ConfigMap。
- `rag-secrets` Secret。
- PostgreSQL、Redis、Milvus 和对象存储服务。
- Ingress、TLS 证书和域名。
- 持久卷和备份策略。

示例：

```bash
kubectl apply -f deploy/kubernetes/api.yaml
kubectl apply -f deploy/kubernetes/web.yaml
kubectl apply -f deploy/kubernetes/reranker.yaml
```

生产环境还应增加：

- Readiness / Liveness Probe。
- Horizontal Pod Autoscaler。
- PodDisruptionBudget。
- NetworkPolicy。
- Secret Manager 或 External Secrets。
- 数据库、向量库和对象存储备份。

## 安全说明

### 不应提交的内容

以下文件和目录已被 `.gitignore` 排除：

- `.env`
- 私钥、证书和 Secret 文件。
- `data/raw/`
- `data/processed/`
- `data/assets/`
- `data/reports/`
- `data/test-runs/`
- IDE、缓存、构建和本地数据库文件。

提交代码前建议执行：

```bash
git status --short
git diff --check
git grep -n "replace-with-real-secret"
```

### 生产建议

- 使用随机生成的 JWT、Bootstrap 和资源签名密钥。
- 使用独立数据库账号和最小权限原则。
- API Key 只在创建时显示一次，服务端仅保存哈希。
- 为 PostgreSQL、Redis、Milvus 和 MinIO 开启认证与网络隔离。
- 使用 HTTPS。
- 限制上传文件大小和允许的扩展名。
- 为模型网关补充超时、重试、熔断和降级策略。
- 定期轮换所有外部服务密钥。
- 不要将真实内部文档、评测集或用户反馈提交到公开仓库。

## 当前边界

当前代码已经实现完整 MVP 主链路，但以下能力仍需要根据生产环境补充：

- 文档列表、详情、删除、版本更新及向量同步删除接口。
- 大文件异步入库任务、任务进度和失败重试队列。
- SSE 或 WebSocket 流式回答。
- 会话列表和管理后台。
- MinIO 多副本部署的完整验收。
- PostgreSQL 正式版本化迁移工具。
- 模型网关熔断、降级和全链路重试策略。
- 完整 Grafana Dashboard 和告警规则。
- CI/CD、镜像签名、自动回滚和灾备演练。
- 基于线上反馈自动构建 Bad Case 评测集。

## 开发约定

- Python 版本范围：`>=3.11,<3.13`。
- 保持组件依赖通过协议和 Container 注入，不在业务逻辑中直接创建基础设施连接。
- 新增 Provider 时同时更新：
  - `rag_core/config.py`
  - `apps/api/app/core/container.py`
  - `.env.example`
  - 对应单元测试
- 修改检索策略时增加离线 Recall / MRR 对比，不仅依赖人工体验。
- 修改 Embedding 模型或维度时创建新 Milvus Collection 并重新入库。
- 不在代码、README、测试或提交历史中写入真实密钥和个人开发机路径。

---

如需快速理解代码，建议按以下顺序阅读：

1. `packages/rag_core/src/rag_core/services.py`
2. `packages/rag_core/src/rag_core/retrieval/retriever.py`
3. `packages/rag_core/src/rag_core/ingestion/chunker.py`
4. `packages/rag_core/src/rag_core/infrastructure/milvus.py`
5. `apps/api/app/core/container.py`
6. `apps/api/app/api/routes/`
7. `apps/web/app/page.tsx`
