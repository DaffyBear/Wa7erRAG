import pytest
from rag_core.infrastructure.memory import InMemoryVectorStore
from rag_core.models import DocumentChunk


@pytest.mark.asyncio
async def test_vector_search_count_and_delete_are_tenant_scoped() -> None:
    store = InMemoryVectorStore()
    await store.ensure_schema(2)
    a = DocumentChunk("a", "doc-a", "a.md", 0, "A", "A", {"tenant_id": "tenant-a"})
    b = DocumentChunk("b", "doc-b", "b.md", 0, "B", "B", {"tenant_id": "tenant-b"})
    await store.upsert([a, b], [[1.0, 0.0], [1.0, 0.0]])
    assert [hit.chunk.chunk_id for hit in await store.search([1.0, 0.0], 10, "tenant-a")] == ["a"]
    assert await store.count("tenant-a") == 1
    assert await store.get_document_chunks(["doc-b"], "tenant-a") == []
    await store.delete_document("doc-a", "tenant-b")
    assert await store.count("tenant-a") == 1
    await store.delete_document("doc-a", "tenant-a")
    assert await store.count("tenant-a") == 0


@pytest.mark.asyncio
async def test_trace_repository_rejects_cross_tenant_feedback() -> None:
    from rag_core.infrastructure.memory import InMemoryTraceRepository
    from rag_core.models import Feedback, MessageTrace

    repository = InMemoryTraceRepository()
    trace = MessageTrace("message", "session", "q", "q", "a", [], {}, "tenant-a", "user-a")
    await repository.save_message(trace)
    with pytest.raises(KeyError):
        await repository.save_feedback(Feedback("feedback", "message", 1, "", "tenant-b", "user-b"))
