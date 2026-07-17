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
