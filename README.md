# Enterprise RAG

工程级内部技术知识库，完整覆盖文档清洗、语义增强、向量入库、父子文档召回、Rerank、生成引用、图片存储、用户反馈、评测和生产部署。

## 当前能力

- DOCX、Markdown、HTML、TXT 解析，DOCX 图片提取。
- 可扩展正则清洗与清洗统计。
- 干净 Markdown 与 Word 双版本输出。
- 摘要、关键词、候选问题语义增强。
- 6000 字短文整篇入库，长文使用 6000/500 递归切分。
- Qwen3-Embedding-8B 1024 维生产适配器与确定性 Mock Embedding。
- Milvus HNSW Schema、维度校验、Top-20 向量召回。
- 命中切片后按父文档拉齐全部 Chunk，再进行 Rerank。
- Query Rewrite、HyDE 假设答案、原查询/改写查询/HyDE 三路 RRF 融合召回。
- 答案生成、引用、Markdown 图片 URL 替换。
- Redis 分布式会话历史、自动续租任务锁和滑动窗口接口限流。
- PostgreSQL 消息与反馈存储、Redis 缓存适配器、MinIO 对象存储。
- FastAPI 上传、问答、反馈、统计、健康检查与 Prometheus 指标 API。
- Next.js 对话、上传、引用、点赞和点踩界面。
- Recall@K、MRR 评测 CLI，Docker Compose 与 Kubernetes 清单。



## Mock 模式

`.env` 中设置 `RAG_USE_MOCKS=true` 时，无需安装 Milvus、PostgreSQL、Redis、MinIO 或 GPU 模型服务即可运行完整链路。

```bat
copy .env.example .env
scripts\run_api.cmd
```

API 文档：`http://localhost:8000/docs`

## 文档入库

```bat
scripts\ingest.cmd data\raw
```

也可调用 `POST /api/v1/documents/upload` 上传单份文件。

## 评测

```bat
scripts\evaluate.cmd evaluation\dataset.example.json
scripts\test.cmd
```

## 生产模式

将 `RAG_USE_MOCKS=false`，并配置模型网关、Milvus、PostgreSQL、Redis、MinIO 和 Rerank 服务地址。Embedding Collection 维度不是 1024 时系统会拒绝复用，必须显式重建，避免静默污染向量数据。
