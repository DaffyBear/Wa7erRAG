import pytest
from rag_core.infrastructure import InMemoryVectorStore
from rag_core.ingestion import DeterministicHashEmbedder
from rag_core.models import DocumentChunk
from rag_core.retrieval import LexicalReranker, ParentDocumentRetriever


@pytest.mark.asyncio
async def test_rrf_fuses_query_and_hyde_routes() -> None:
    embedder = DeterministicHashEmbedder(128)
    store = InMemoryVectorStore()
    chunks = [
        DocumentChunk(
            "mqtt", "mqtt", "mqtt.md", 0, "服务监听端口为1883", "MQTT broker 监听端口 1883"
        ),
        DocumentChunk(
            "http", "http", "http.md", 0, "服务监听端口为8080", "HTTP server 监听端口 8080"
        ),
    ]
    await store.ensure_schema(128)
    await store.upsert(chunks, await embedder.embed([item.embedding_text for item in chunks]))
    retriever = ParentDocumentRetriever(
        embedder, store, LexicalReranker(), vector_top_k=2, final_top_k=2
    )
    results = await retriever.retrieve(
        "消息服务端口是多少",
        ["MQTT broker默认监听1883端口，配置项用于设置服务端监听地址"],
    )
    mqtt = next(item for item in results if item.document_id == "mqtt")
    assert "variant_1" in mqtt.metadata["matched_routes"]
    assert mqtt.metadata["rrf_score"] > 0
    assert len(mqtt.metadata["search_variants"]) == 2
