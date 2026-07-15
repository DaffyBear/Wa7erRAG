import pytest
from rag_core.infrastructure import InMemoryVectorStore
from rag_core.ingestion import DeterministicHashEmbedder
from rag_core.models import DocumentChunk
from rag_core.retrieval import LexicalReranker, ParentDocumentRetriever


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
