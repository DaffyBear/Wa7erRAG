from collections.abc import Sequence

import pytest
from rag_core.infrastructure import InMemoryVectorStore
from rag_core.ingestion import DeterministicHashEmbedder
from rag_core.models import DocumentChunk, RetrievalResult
from rag_core.retrieval import LexicalReranker, ParentDocumentRetriever


class RecordingReranker(LexicalReranker):
    def __init__(self) -> None:
        self.candidate_count = 0

    async def rerank(
        self, query: str, candidates: Sequence[RetrievalResult]
    ) -> list[RetrievalResult]:
        self.candidate_count = len(candidates)
        return await super().rerank(query, candidates)


@pytest.mark.asyncio
async def test_parent_recall_expands_all_chunks() -> None:
    embedder = DeterministicHashEmbedder(64)
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk("a0", "a", "guide.md", 0, "MQTT 简介", "MQTT 简介"),
        DocumentChunk("a1", "a", "guide.md", 1, "端口参数为1883", "端口参数为1883"),
        DocumentChunk("b0", "b", "other.md", 0, "数据库配置", "数据库配置"),
    ]
    await store.ensure_schema(64)
    await store.upsert(chunks, await embedder.embed([item.embedding_text for item in chunks]))
    retriever = ParentDocumentRetriever(
        embedder, store, LexicalReranker(), vector_top_k=2, final_top_k=2
    )
    results = await retriever.retrieve("MQTT端口参数")
    target = next(item for item in results if item.document_id == "a")
    assert "MQTT 简介" in target.content
    assert "1883" in target.content
    assert [item.chunk_index for item in target.chunks] == [0, 1]


@pytest.mark.asyncio
async def test_rerank_candidates_are_capped_after_route_fusion() -> None:
    embedder = DeterministicHashEmbedder(64)
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk(
            f"chunk-{index}",
            f"doc-{index}",
            f"doc-{index}.md",
            0,
            f"MQTT configuration {index}",
            f"MQTT configuration {index}",
        )
        for index in range(12)
    ]
    await store.ensure_schema(64)
    await store.upsert(chunks, await embedder.embed([item.embedding_text for item in chunks]))
    reranker = RecordingReranker()
    retriever = ParentDocumentRetriever(
        embedder,
        store,
        reranker,
        vector_top_k=12,
        rerank_candidate_count=5,
        final_top_k=3,
    )
    results = await retriever.retrieve("MQTT configuration", ["MQTT setup"])
    assert reranker.candidate_count == 5
    assert len(results) == 3


@pytest.mark.asyncio
async def test_bm25_route_recalls_exact_identifier() -> None:
    embedder = DeterministicHashEmbedder(64)
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk(
            "exact",
            "exact-doc",
            "errors.md",
            0,
            "设备返回错误码 E_CONN_1042，需要检查证书链。",
            "无关的向量嵌入文本",
        ),
        DocumentChunk(
            "semantic",
            "semantic-doc",
            "network.md",
            0,
            "网络连接失败的通用处理方法。",
            "E_CONN_1042 E_CONN_1042 E_CONN_1042",
        ),
    ]
    await store.ensure_schema(64)
    await store.upsert(chunks, await embedder.embed([item.embedding_text for item in chunks]))
    retriever = ParentDocumentRetriever(
        embedder,
        store,
        LexicalReranker(),
        vector_top_k=1,
        lexical_top_k=2,
        final_top_k=2,
    )

    results = await retriever.retrieve("E_CONN_1042")

    exact = next(item for item in results if item.document_id == "exact-doc")
    assert "bm25_query" in exact.metadata["matched_routes"]
    assert exact.metadata["bm25_score"] > 0


@pytest.mark.asyncio
async def test_hybrid_search_can_be_disabled() -> None:
    embedder = DeterministicHashEmbedder(64)
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk("a", "a", "a.md", 0, "ONLY_BM25_TOKEN", "semantic target"),
        DocumentChunk("b", "b", "b.md", 0, "other", "ONLY_BM25_TOKEN"),
    ]
    await store.ensure_schema(64)
    await store.upsert(chunks, await embedder.embed([item.embedding_text for item in chunks]))
    retriever = ParentDocumentRetriever(
        embedder,
        store,
        LexicalReranker(),
        vector_top_k=1,
        final_top_k=2,
        hybrid_enabled=False,
    )

    results = await retriever.retrieve("ONLY_BM25_TOKEN")

    assert all(not item.metadata["lexical_variants"] for item in results)
    assert all(
        not any(route.startswith("bm25") for route in item.metadata["matched_routes"])
        for item in results
    )


@pytest.mark.asyncio
async def test_bm25_search_respects_tenant_scope() -> None:
    embedder = DeterministicHashEmbedder(64)
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk(
            "tenant-a",
            "doc-a",
            "a.md",
            0,
            "共享错误码 X900",
            "a",
            {"tenant_id": "tenant-a"},
        ),
        DocumentChunk(
            "tenant-b",
            "doc-b",
            "b.md",
            0,
            "共享错误码 X900",
            "b",
            {"tenant_id": "tenant-b"},
        ),
    ]
    await store.ensure_schema(64)
    await store.upsert(chunks, await embedder.embed([item.embedding_text for item in chunks]))

    hits = await store.lexical_search("X900", 10, tenant_id="tenant-a")

    assert [hit.chunk.document_id for hit in hits] == ["doc-a"]
