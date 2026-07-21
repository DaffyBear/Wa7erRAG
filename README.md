# WA7ER RAG

**English** | [中文](README.zh-CN.md)

A production-oriented Retrieval-Augmented Generation platform for enterprise technical documents. It covers document governance, cleaning, dual-format export, semantic enrichment, hybrid retrieval, parent-document expansion, reranking, streamed answer generation, traceable citations, multi-tenant security, persistent conversations, feedback loops, offline evaluation, observability, and containerized deployment.

The core RAG pipeline is implemented without LangChain or LlamaIndex. Replaceable protocols and a lightweight service layer provide direct control over data processing, retrieval behavior, failure handling, and infrastructure integration.

> This repository contains no real API keys, database passwords, private documents, user data, or local runtime artifacts. Sensitive configuration is loaded from an untracked `.env` file.

## Product Preview

> The visual style reflects the author's personal preferences. Conversation titles shown in the history panel are test data only and carry no additional implication.

### Login

![Login screen](docs/images/login-screen.png)

### Chat Workspace — Conversation

![Chat workspace with RAG response](docs/images/chat-conversation-screen-v3.png)

### Chat Workspace — Empty State

![Chat workspace before conversation](docs/images/chat-empty-screen-v3.png)

## Table of Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [RAG Workflows](#rag-workflows)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Runtime Modes](#runtime-modes)
- [Environment Variables](#environment-variables)
- [Infrastructure](#infrastructure)
- [Administrator Bootstrap](#administrator-bootstrap)
- [Document Ingestion](#document-ingestion)
- [Chat API](#chat-api)
- [Main API Endpoints](#main-api-endpoints)
- [Offline Evaluation](#offline-evaluation)
- [Data Governance](#data-governance)
- [Monitoring](#monitoring)
- [Testing](#testing)
- [Docker Deployment](#docker-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Security](#security)
- [Current Limitations](#current-limitations)
- [Development Conventions](#development-conventions)

## Highlights

### Document Processing

- Supports PDF, DOCX, Markdown, HTML, and plain-text documents.
- Extracts embedded DOCX images and PDF page images.
- Cleans page metadata, forum markers, timestamps, numeric-only noise, compatibility messages, and other configurable patterns.
- Produces two outputs for each document:
  - Clean Markdown for indexing and machine processing.
  - Clean DOCX for human-readable source review.
- Records matched cleaning rules, text length, and processing status.
- Uses checksums and checkpoints to skip unchanged documents while supporting forced reprocessing.

### Semantic Enrichment

Each document can be enriched with:

- A one-sentence summary.
- Key technical terms.
- Questions the document can answer.

Enrichment can use either deterministic heuristics or an OpenAI-compatible model gateway. Question metadata improves alignment between natural user queries and document content.

### Chunking Strategy

- Documents below `RAG_SHORT_DOCUMENT_LIMIT` remain intact to preserve semantics.
- Longer documents use recursive character splitting.
- Default settings:
  - Chunk size: `6000`
  - Chunk overlap: `500`
- Embedding text includes the title, summary, keywords, and answerable questions.
- Original content is stored separately from enriched embedding text so citations remain clean.

### Retrieval and Generation

- Retrieval Router: rules handle obvious cases first; ambiguous queries are sent to a lightweight model that returns only a `needs_retrieval` JSON decision. Failures default to retrieval.
- Query Rewrite: converts context-dependent follow-up questions into standalone queries only when retrieval is required.
- HyDE: creates a hypothetical answer as an additional dense retrieval query.
- Multi-route retrieval combines the original query, rewritten query, and HyDE query.
- Milvus native BM25 lexical search is fused with dense retrieval at document level.
- Reciprocal Rank Fusion merges multiple ranked result lists.
- Parent-document expansion retrieves every chunk of a document when any child chunk matches, then restores chunk order.
- Milvus HNSW indexing includes embedding-dimension and collection-schema validation.
- Supports lexical reranking and external HTTP rerank services.
- Default rerank candidate count is `20`; final context count is `5`.
- General conversation can bypass the knowledge base and call the generation model directly.
- Responses expose rewritten queries, citations, relevance scores, route decisions, and stage timings.

### Application and Security

- PostgreSQL persists sessions, messages, retrieval traces, feedback, users, tenants, API keys, and audit events.
- Redis provides session state, answer caching, sliding-window rate limits, and distributed locks.
- JWT and API-key authentication.
- Tenant-level data isolation.
- Role- and permission-based endpoint authorization.
- Helpful / Needs Work feedback with optional reasons.
- Request IDs, security auditing, and Prometheus metrics.

### Web Application

- Next.js single-page application.
- Tenant, username, and password login.
- Persistent conversation history with rename and delete operations.
- Document upload and ingestion status.
- Multi-turn streamed chat with reusable session IDs.
- Query rewrite display and per-stage timing dashboard.
- Markdown, code, links, images, and source citations.
- Helpful / Needs Work feedback interactions.
- Keyboard navigation across answers.

## Architecture

```mermaid
flowchart LR
    U["Browser / API Client"] --> W["Next.js Web"]
    W --> A["FastAPI API"]
    U --> A

    A --> S["Security Service"]
    A --> I["Ingestion Service"]
    A --> R["RAG Service"]
    A --> G["Governance Service"]

    S --> PG["PostgreSQL"]
    I --> OS["Local Store / MinIO"]
    I --> M["Milvus"]
    R --> M
    R --> RD["Redis"]
    R --> PG
    R --> MG["Model Gateway"]
    R --> RR["Rerank Service"]
    G --> FS["Governance Reports"]
```

Core design principles:

- Infrastructure is accessed through protocols and dependency injection.
- Providers can be replaced independently.
- Mock and production providers share the same application workflow.
- Tenant identity is propagated through storage, retrieval, caching, and tracing.
- Intermediate retrieval data is persisted for evaluation and debugging.

## RAG Workflows

### Ingestion Workflow

```mermaid
flowchart LR
    A["Source Document"] --> B["Parse text and assets"]
    B --> C["Rule-based cleaning"]
    C --> D["Markdown + DOCX export"]
    C --> E["Semantic enrichment"]
    E --> F["Short-document or recursive chunking"]
    F --> G["Embedding generation"]
    G --> H["Milvus dense + sparse indexing"]
    D --> I["Local Store / MinIO"]
    H --> J["Checkpoint update"]
```

### Query Workflow

```mermaid
flowchart LR
    Q["User Query"] --> RT["Retrieval Router"]
    RT -->|Direct| LLM["Generation Model"]
    RT -->|Retrieve| RW["Query Rewrite"]
    RW --> HY["Conditional HyDE"]
    Q --> DR["Dense Retrieval"]
    RW --> DR
    HY --> DR
    Q --> BM["BM25 Retrieval"]
    RW --> BM
    DR --> RF["Document-level RRF"]
    BM --> RF
    RF --> PE["Parent-document Expansion"]
    PE --> RR["Rerank"]
    RR --> CTX["Final Context"]
    CTX --> LLM
    LLM --> ANS["Streamed Answer + Citations"]
    ANS --> TR["PostgreSQL Trace + Feedback"]
```

HyDE is skipped when the rewritten query is shorter than the configured threshold. This avoids unnecessary latency for short or already explicit queries.

### General Conversation Route

Questions such as greetings, model identity, or general conversation can bypass retrieval. The router decides whether the knowledge base is needed, allowing RAG to enhance domain answers without forcing every message through document search.

## Technology Stack

| Layer | Technologies |
|---|---|
| Web | Next.js 16, React 19, TypeScript |
| API | FastAPI, Pydantic, Uvicorn |
| RAG Core | Python 3.11+, protocol-based services |
| Vector Database | Milvus, HNSW, native BM25 sparse vectors |
| Relational Database | PostgreSQL, SQLAlchemy AsyncIO, asyncpg |
| State and Cache | Redis |
| Object Storage | Local signed storage or MinIO |
| Model Integration | OpenAI-compatible HTTP APIs |
| Reranking | External HTTP reranker with lexical fallback |
| Observability | Prometheus, structured logs, request audit records |
| Deployment | Docker Compose and Kubernetes examples |
| Testing | pytest, Ruff, mypy, TypeScript compiler |

## Project Structure

```text
RAG_v1/
├─ apps/
│  ├─ api/                     # FastAPI application and HTTP routes
│  └─ web/                     # Next.js frontend
├─ packages/rag_core/          # Cleaning, ingestion, retrieval, generation and security
├─ pipelines/                  # Ingestion, governance and migration commands
├─ evaluation/                 # Offline evaluation datasets and runner
├─ migrations/                 # PostgreSQL initialization SQL
├─ configs/                    # Cleaning and RAG configuration
├─ deploy/
│  ├─ docker/                  # Dockerfiles and Compose manifests
│  ├─ kubernetes/              # Kubernetes examples
│  └─ monitoring/              # Prometheus configuration
├─ docs/                       # Architecture, security and infrastructure guides
├─ scripts/                    # Windows helper scripts
├─ tests/                      # Unit and integration tests
├─ data/                       # Local runtime data, ignored by Git
├─ .env.example
├─ README.md                   # English documentation
└─ README.zh-CN.md             # Chinese documentation
```

## Quick Start

### Prerequisites

- Python `>=3.11,<3.13`
- Node.js 22+
- npm
- Docker Desktop for production infrastructure
- Conda is recommended on Windows

### 1. Clone the Repository

```bash
git clone https://github.com/DaffyBear/Wa7erRAG.git
cd Wa7erRAG
```

### 2. Create the Python Environment

Using Conda:

```bash
conda env create -f environment.yml
conda activate RAG_E
```

Using `venv`:

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

### 3. Install Backend Dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 4. Install Frontend Dependencies

```bash
cd apps/web
npm install
cd ../..
```

### 5. Create Local Configuration

Windows:

```bat
copy .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Never commit `.env`. At minimum, replace these values:

```env
SECURITY_JWT_SECRET=replace-with-a-long-random-secret
SECURITY_BOOTSTRAP_TOKEN=replace-with-a-one-time-bootstrap-token
SECURITY_ASSET_SIGNING_SECRET=replace-with-another-random-secret
```

### 6. Start in Mock Mode

Mock mode requires no PostgreSQL, Redis, Milvus, MinIO, or external model APIs:

```env
RAG_USE_MOCKS=true
RAG_METADATA_PROVIDER=auto
RAG_EMBEDDING_PROVIDER=auto
RAG_VECTOR_STORE_PROVIDER=auto
RAG_OBJECT_STORE_PROVIDER=auto
RAG_ROUTER_PROVIDER=auto
RAG_REWRITE_PROVIDER=auto
RAG_HYDE_PROVIDER=auto
RAG_RERANK_PROVIDER=auto
RAG_GENERATION_PROVIDER=auto
RAG_TRACE_PROVIDER=auto
RAG_SECURITY_PROVIDER=auto
RAG_STATE_PROVIDER=auto
```

Start the API in PowerShell:

```powershell
$env:PYTHONPATH="packages\rag_core\src;apps\api"
conda run -n RAG_E python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --reload
```

Linux/macOS:

```bash
PYTHONPATH=packages/rag_core/src:apps/api \
python -m uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --reload
```

Start the web application:

```bash
cd apps/web
npm run dev
```

Open:

- Web: `http://localhost:3000`
- API documentation: `http://localhost:8000/docs`
- Health endpoint: `http://localhost:8000/api/v1/health`
- Prometheus metrics: `http://localhost:8000/api/v1/metrics`

### Windows Start and Stop Scripts

```bat
scripts\start_all.cmd
```

```bat
scripts\stop_all.cmd
```

The scripts manage Redis, Milvus, Attu, API, and Web startup while checking PostgreSQL. Default ports are Web `3000`, API `8000`, Attu `8001`, and Milvus `19530`. Runtime logs are written to `tmp\runtime\logs`.

## Runtime Modes

### Global Mock Switch

```env
RAG_USE_MOCKS=true
```

When providers are set to `auto`:

| Component | Mock default | Production default |
|---|---|---|
| Metadata | heuristic | openai |
| Embedding | deterministic | openai |
| Vector Store | memory | milvus |
| Object Store | local | minio |
| Router | rule | openai |
| Rewrite | heuristic | openai |
| HyDE | heuristic | openai |
| Rerank | lexical | http |
| Generation | extractive | openai |
| Trace | memory | postgres |
| Security | memory | postgres |
| State | memory | redis |

### Per-provider Overrides

Real infrastructure can be enabled incrementally even when `RAG_USE_MOCKS=true`:

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

## Environment Variables

Copy `.env.example` and use it as the authoritative list.

### Application and Security

| Variable | Purpose |
|---|---|
| `APP_NAME` | Application name |
| `APP_ENV` | Runtime environment |
| `APP_DEBUG` | Debug mode |
| `LOG_LEVEL` | Logging level |
| `SECURITY_ENABLED` | Enables authentication and authorization |
| `SECURITY_JWT_SECRET` | JWT signing secret; must be replaced in production |
| `SECURITY_JWT_ISSUER` | JWT issuer |
| `SECURITY_JWT_AUDIENCE` | JWT audience |
| `SECURITY_ACCESS_TOKEN_TTL_SECONDS` | Access-token lifetime |
| `SECURITY_BOOTSTRAP_TOKEN` | One-time administrator bootstrap token |
| `SECURITY_ASSET_SIGNING_SECRET` | Local asset URL signing secret |

### Providers

| Variable | Supported values |
|---|---|
| `RAG_METADATA_PROVIDER` | `auto` / `heuristic` / `openai` |
| `RAG_EMBEDDING_PROVIDER` | `auto` / `deterministic` / `openai` |
| `RAG_VECTOR_STORE_PROVIDER` | `auto` / `memory` / `milvus` |
| `RAG_OBJECT_STORE_PROVIDER` | `auto` / `local` / `minio` |
| `RAG_ROUTER_PROVIDER` | `auto` / `rule` / `openai` |
| `RAG_REWRITE_PROVIDER` | `auto` / `heuristic` / `openai` |
| `RAG_HYDE_PROVIDER` | `auto` / `heuristic` / `openai` |
| `RAG_RERANK_PROVIDER` | `auto` / `lexical` / `http` |
| `RAG_GENERATION_PROVIDER` | `auto` / `extractive` / `openai` |
| `RAG_TRACE_PROVIDER` | `auto` / `memory` / `postgres` |
| `RAG_SECURITY_PROVIDER` | `auto` / `memory` / `postgres` |
| `RAG_STATE_PROVIDER` | `auto` / `memory` / `redis` |

### Model Configuration

```env
MODEL_GATEWAY_BASE_URL=https://model-gateway.example.com/v1
MODEL_GATEWAY_API_KEY=replace-with-model-api-key

RAG_EMBEDDING_MODEL=your-embedding-model
RAG_EMBEDDING_DIMENSION=1024
RAG_GENERATION_MODEL=your-chat-model
RAG_ROUTER_MODEL=your-lightweight-chat-model
RAG_REWRITE_MODEL=your-lightweight-chat-model
RAG_HYDE_MODEL=your-lightweight-chat-model
```

The model gateway must expose OpenAI-compatible endpoints. Once an embedding dimension is used to create a Milvus collection, changing it requires a new collection and re-ingestion.

### Rerank Configuration

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

The HTTP reranker client provides:

- Shared HTTP connection pooling.
- Semaphore-based concurrency limits.
- Queue timeouts.
- Exponential-backoff retries for network errors, timeouts, `408`, `425`, `429`, and `5xx` responses.
- `Retry-After` support.
- Closed, Open, and Half-Open circuit-breaker states.
- Lexical fallback for remote failures or malformed responses.
- Candidate truncation to control request size and inference cost.
- Provider, model, fallback reason, retry, latency, and circuit-state metrics.

Set `RERANK_FALLBACK_PROVIDER=none` to disable fallback and propagate remote rerank failures.

### Retrieval Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `RAG_SHORT_DOCUMENT_LIMIT` | `6000` | Whole-document threshold |
| `RAG_CHUNK_SIZE` | `6000` | Long-document chunk size |
| `RAG_CHUNK_OVERLAP` | `500` | Chunk overlap |
| `RAG_VECTOR_TOP_K` | `20` | Dense candidates per query route |
| `RAG_ROUTER_ENABLED` | `true` | Enables retrieval routing |
| `RAG_ROUTER_MODEL` | `deepseek-v4-flash` | Model returning retrieval decision JSON |
| `RAG_ROUTER_TIMEOUT_SECONDS` | `5` | Router timeout; failures default to retrieval |
| `RAG_HYBRID_SEARCH_ENABLED` | `true` | Enables Dense + BM25 retrieval |
| `RAG_LEXICAL_TOP_K` | `20` | BM25 candidates per lexical route |
| `RAG_RERANK_CANDIDATE_COUNT` | `20` | Rerank candidate count |
| `RAG_FINAL_TOP_K` | `5` | Final context count |
| `RAG_HYDE_ENABLED` | `true` | Enables conditional HyDE |
| `RAG_HNSW_M` | `16` | HNSW M |
| `RAG_HNSW_EF_CONSTRUCTION` | `256` | HNSW construction parameter |
| `RAG_HNSW_EF_SEARCH` | `64` | HNSW query parameter |

## Infrastructure

### PostgreSQL

```env
POSTGRES_DSN=postgresql+asyncpg://rag_user:strong-password@localhost:5432/enterprise_rag
```

PostgreSQL stores tenants, users, memberships, API keys, audit events, sessions, messages, retrieval traces, and feedback. Use a dedicated least-privilege database owner rather than a PostgreSQL superuser.

The application can initialize repository schemas for development. Production deployments should apply versioned SQL from `migrations/` through a controlled migration process.

### Redis

```env
RAG_STATE_PROVIDER=redis
REDIS_URL=redis://localhost:6379/0
```

Redis is used for:

- Conversation state and TTL.
- Answer caching.
- Login, chat, and upload rate limiting.
- Distributed ingestion locks.

The API pings Redis during startup and refuses to start when the configured backend is unavailable.

### Milvus

Start Milvus Standalone:

```bash
docker compose -p enterprise-rag-milvus \
  -f deploy/docker/docker-compose.milvus.yml up -d
```

Windows:

```bat
scripts\start_milvus.cmd
```

Configuration:

```env
RAG_VECTOR_STORE_PROVIDER=milvus
MILVUS_URI=http://localhost:19530
MILVUS_COLLECTION=enterprise_knowledge_hybrid_v2
RAG_HYBRID_SEARCH_ENABLED=true
RAG_LEXICAL_TOP_K=20
RAG_EMBEDDING_DIMENSION=1024
```

The collection contains dense vectors, sparse vectors generated by a Milvus BM25 Function, original text, enriched embedding text, tenant fields, filenames, document IDs, and chunk indexes. The application validates dense dimensions and BM25 schema compatibility instead of silently degrading to dense-only retrieval.

Migrate an older dense collection without calling the embedding API again:

```powershell
scripts\migrate_milvus_hybrid.cmd --source enterprise_knowledge_tenant_v1 --target enterprise_knowledge_hybrid_v2
```

After verification, update `MILVUS_COLLECTION` in `.env`. BM25 uses the original and rewritten queries; HyDE participates only in dense retrieval to avoid weakening exact lexical matches.

### MinIO

```env
RAG_OBJECT_STORE_PROVIDER=minio
MINIO_ENDPOINT=localhost:9001
MINIO_ACCESS_KEY=replace-with-access-key
MINIO_SECRET_KEY=replace-with-secret-key
MINIO_BUCKET=rag-assets
MINIO_SECURE=false
```

Use local signed storage when MinIO is unavailable:

```env
RAG_OBJECT_STORE_PROVIDER=local
```

Local object storage generates HMAC-signed asset URLs. Multi-replica production deployments should use MinIO or a shared persistent volume rather than container-local disks.

## Administrator Bootstrap

Bootstrap is allowed only once. The request token must match `SECURITY_BOOTSTRAP_TOKEN`.

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

Passwords must contain at least 12 characters. Rotate or disable the bootstrap token after initialization.

Login:

```bash
curl -X POST http://localhost:8000/api/v1/security/token \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "replace-with-a-strong-password",
    "tenant_slug": "default"
  }'
```

Use the returned token in subsequent requests:

```text
Authorization: Bearer <access_token>
```

## Document Ingestion

### Supported Formats

- `.pdf`
- `.docx`
- `.md`
- `.markdown`
- `.html`
- `.htm`
- `.txt`

### Upload API

```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload?force=false" \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@./example.pdf"
```

Example response:

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

### CLI Ingestion

PowerShell with the project Conda environment:

```powershell
$env:PYTHONPATH="packages\rag_core\src;apps\api"
conda run -n RAG_E python pipelines/ingest.py data/raw
```

Force reprocessing:

```powershell
conda run -n RAG_E python pipelines/ingest.py data/raw --force
```

Windows helper:

```bat
scripts\ingest.cmd data\raw
```

## Chat API

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How should MQTT be configured?",
    "session_id": null,
    "history": []
  }'
```

The streaming endpoint returns newline-delimited JSON events for route decisions, rewrite output, timings, answer tokens, citations, completion, and errors. Reuse the returned `session_id` for subsequent turns. When explicit history is omitted, the service loads session history from Redis or the in-memory state provider.

A persisted message trace contains:

- Original and rewritten query.
- Retrieved document IDs and relevance scores.
- Route, cache, HyDE, rerank, and fallback metadata.
- Per-stage latency.
- Final answer and citations.
- Tenant and user identity.

## Main API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Health status |
| `GET` | `/api/v1/metrics` | Prometheus metrics |
| `POST` | `/api/v1/security/bootstrap` | One-time administrator bootstrap |
| `POST` | `/api/v1/security/token` | Login and issue JWT |
| `POST` | `/api/v1/documents/upload` | Upload and ingest a document |
| `POST` | `/api/v1/chat` | Execute the streamed RAG workflow |
| `GET` | `/api/v1/chat/sessions` | List persisted conversations |
| `GET` | `/api/v1/chat/sessions/{session_id}` | Load a conversation |
| `PATCH` | `/api/v1/chat/sessions/{session_id}` | Rename a conversation |
| `DELETE` | `/api/v1/chat/sessions/{session_id}` | Delete a conversation and its feedback |
| `POST` | `/api/v1/messages/{message_id}/feedback` | Store user feedback |
| `GET` | `/api/v1/assets/{path}` | Access a signed local asset |
| `POST` | `/api/v1/governance/runs` | Start a governance run |

## Offline Evaluation

Evaluation datasets are stored under `evaluation/`.

```bash
conda run -n RAG_E python evaluation/evaluate.py \
  --dataset evaluation/dataset.json \
  --output data/reports/evaluation.json
```

The evaluation workflow can measure:

- Recall@K.
- Mean Reciprocal Rank.
- Retrieval latency.
- Rerank latency and fallback rate.
- Answer source coverage.
- Routing and HyDE decisions.

Build evaluation cases from real, anonymized questions and label the correct source documents. Retrieval configuration should be changed based on measured results rather than intuition alone.

## Data Governance

The governance pipeline inventories files, samples documents, records parse and cleaning results, and compares runs.

```bash
conda run -n RAG_E python pipelines/governance.py data/raw
```

Generated reports are stored under `data/reports/`, which is excluded from Git.

## Monitoring

Prometheus configuration is available in `deploy/monitoring/`.

Important metrics include:

- API request rate, errors, and P99 latency.
- Retrieval, rerank, first-token, and generation latency.
- Rerank retries, fallback rate, circuit state, and candidate count.
- Milvus query latency and memory usage.
- Redis and PostgreSQL availability.
- Model token usage.
- Empty retrieval rate, negative-feedback rate, and bad-case count.

## Testing

Always run Python commands in the `RAG_E` Conda environment:

```bash
conda run -n RAG_E python -m ruff check packages apps tests
conda run -n RAG_E python -m pytest -q
```

Frontend type check and production build:

```bash
cd apps/web
npx tsc --noEmit --incremental false
npm run build
```

Coverage includes:

- Cleaning rules and dual-format exports.
- PDF parsing and asset extraction.
- Short- and long-document chunking.
- Dense, BM25, RRF, and parent-document retrieval.
- HTTP reranking, retries, circuit breaking, and fallback.
- Query rewrite, routing, and HyDE.
- Redis-like sessions, caching, rate limits, and distributed locks.
- Multi-tenant isolation.
- Users, roles, JWT, API keys, and auditing.
- Persistent conversation management.
- FastAPI integration and end-to-end RAG flow.

## Docker Deployment

Start PostgreSQL, Redis, MinIO, API, and Web:

```bash
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

Start Milvus separately:

```bash
docker compose -p enterprise-rag-milvus \
  -f deploy/docker/docker-compose.milvus.yml up -d
```

Use Compose service names inside containers:

```env
POSTGRES_DSN=postgresql+asyncpg://rag:strong-password@postgres:5432/rag
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
MILVUS_URI=http://milvus-standalone:19530
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

Separate Compose projects do not automatically share a Docker network. Merge the manifests or configure an explicit shared network for production.

## Kubernetes Deployment

Example manifests are under `deploy/kubernetes/`:

- `api.yaml`: three FastAPI replicas.
- `web.yaml`: two Next.js replicas.
- `reranker.yaml`: GPU reranker workload example.

Before deployment, create:

- `rag-config` ConfigMap.
- `rag-secrets` Secret.
- PostgreSQL, Redis, Milvus, and object-storage services.
- Ingress, TLS certificates, and DNS.
- Persistent volumes and backup policies.

```bash
kubectl apply -f deploy/kubernetes/api.yaml
kubectl apply -f deploy/kubernetes/web.yaml
kubectl apply -f deploy/kubernetes/reranker.yaml
```

Production deployments should additionally provide readiness, liveness, and startup probes; Horizontal Pod Autoscaling; PodDisruptionBudgets; NetworkPolicies; external secret management; and tested backup and restore procedures.

## Security

### Files That Must Not Be Committed

The following are excluded through `.gitignore`:

- `.env`
- Private keys, certificates, and secret files.
- Private design and research guidance documents.
- `data/raw/`
- `data/processed/`
- `data/assets/`
- `data/reports/`
- `data/test-runs/`
- IDE, cache, build, and local database artifacts.

Before committing:

```bash
git status --short
git diff --check
git grep -n "replace-with-real-secret"
```

### Production Recommendations

- Generate unique JWT, bootstrap, and asset-signing secrets.
- Use dedicated database accounts with least privilege.
- Display API keys only once and store only hashes server-side.
- Enable authentication and network isolation for PostgreSQL, Redis, Milvus, and MinIO.
- Use HTTPS everywhere.
- Restrict upload size and permitted extensions.
- Add timeouts, retry budgets, circuit breakers, and fallbacks to all model-gateway calls.
- Rotate external credentials regularly.
- Never publish real internal documents, evaluation sets, feedback, or user data.
- Replace browser localStorage tokens with secure HttpOnly cookies before public deployment.

## Current Limitations

The primary MVP workflow is operational, but production deployment still requires:

- Versioned PostgreSQL migrations and rollback procedures.
- Real dependency-aware readiness and liveness checks.
- Asynchronous ingestion jobs for large files, progress tracking, retries, and dead-letter handling.
- Full document list, version update, deletion, and synchronized vector deletion APIs.
- Validated multi-replica MinIO or shared object storage.
- Unified model-gateway resilience and request concurrency budgets.
- Complete Grafana dashboards and alert rules.
- CI/CD, image scanning and signing, automated rollback, and disaster-recovery exercises.
- Load tests for concurrency, P95/P99 latency, connection-pool saturation, and degraded dependencies.
- Automated bad-case evaluation-set generation from anonymized feedback.

## Development Conventions

- Python version: `>=3.11,<3.13`.
- Run Python, pytest, migration, and ingestion commands through `conda run -n RAG_E` on this project machine.
- Inject dependencies through protocols and the application container; do not create infrastructure clients inside business logic.
- When adding a provider, update:
  - `packages/rag_core/src/rag_core/config.py`
  - `apps/api/app/core/container.py`
  - `.env.example`
  - Relevant unit and integration tests
- Compare Recall / MRR before and after retrieval changes.
- Create a new Milvus collection and re-ingest when changing embedding model or dimensions.
- Never write real credentials or personal machine paths into code, documentation, tests, or commit history.

## Recommended Reading Order

1. `packages/rag_core/src/rag_core/services.py`
2. `packages/rag_core/src/rag_core/retrieval/retriever.py`
3. `packages/rag_core/src/rag_core/retrieval/router.py`
4. `packages/rag_core/src/rag_core/ingestion/chunker.py`
5. `packages/rag_core/src/rag_core/infrastructure/milvus.py`
6. `packages/rag_core/src/rag_core/infrastructure/postgres.py`
7. `apps/api/app/core/container.py`
8. `apps/api/app/api/routes/`
9. `apps/web/app/page.tsx`