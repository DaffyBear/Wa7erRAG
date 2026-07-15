# Architecture

## Runtime Flow

1. Query Rewrite 将多轮问题改写为自包含查询。
2. 原查询、改写查询和可选 HyDE 查询进入 Embedding。
3. Milvus HNSW 获取 Top-20 切片。
4. 根据 `document_id` 拉取命中文档全部切片并按 `chunk_index` 重组。
5. `bge-reranker-v2-m3` 对父文档候选精排。
6. Qwen2.5-72B 基于上下文生成带引用回答。
7. 图片本地路径根据映射替换为 MinIO HTTP URL。
8. PostgreSQL 保存消息、召回结果、耗时和反馈，Redis 管理缓存与会话状态。

## Dependency Boundary

核心包只依赖协议和领域模型。Milvus、模型网关、MinIO、PostgreSQL 与 Redis 都通过适配器接入，Mock 模式与生产模式共享同一业务编排。

## Fixed Decisions

- Embedding：Qwen3-Embedding-8B，1024 维。
- 短文档阈值：6000 字符。
- 长文档切片：6000 字符，重叠 500 字符。
- HNSW：`M=16`，`efConstruction=256`，默认查询 `ef=64`。
- Rerank 候选：Top-20。
- Python Conda 环境：`RAG_E`，仅通过普通 `cmd.exe` 管理。
