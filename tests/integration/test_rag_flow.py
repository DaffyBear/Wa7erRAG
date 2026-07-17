from pathlib import Path

import pytest
from rag_core.cleaning import DualFormatExporter, RegexDocumentCleaner, default_parser_registry
from rag_core.distributed import InMemoryLockManager, InMemorySessionStore
from rag_core.enrichment import HeuristicMetadataEnricher
from rag_core.generation import ExtractiveAnswerGenerator
from rag_core.infrastructure import (
    InMemoryCache,
    InMemoryTraceRepository,
    InMemoryVectorStore,
    LocalObjectStore,
)
from rag_core.ingestion import DeterministicHashEmbedder, RecursiveDocumentChunker
from rag_core.retrieval import HeuristicHydeGenerator, HeuristicQueryRewriter, LexicalReranker
from rag_core.services import IngestionService, RagService


@pytest.mark.asyncio
async def test_mock_ingestion_answer_and_distributed_session(tmp_path: Path) -> None:
    source = tmp_path / "mqtt.md"
    source.write_text("# MQTT配置\n\n服务端口配置为1883。", encoding="utf-8")
    embedder = DeterministicHashEmbedder(128)
    store = InMemoryVectorStore()
    traces = InMemoryTraceRepository()
    sessions = InMemorySessionStore()
    object_store = LocalObjectStore(tmp_path / "assets")
    ingestion = IngestionService(
        default_parser_registry(tmp_path / "extracted"),
        RegexDocumentCleaner(),
        DualFormatExporter(),
        HeuristicMetadataEnricher(),
        RecursiveDocumentChunker(),
        embedder,
        store,
        object_store,
        tmp_path / "processed",
        tmp_path / "checkpoint.json",
        InMemoryLockManager(),
    )
    result = await ingestion.ingest_path(source)
    assert result.chunk_count == 1
    assert result.source_url and result.source_url.startswith("/api/v1/assets/")
    assert result.markdown_url and result.markdown_url.startswith("/api/v1/assets/")
    source_object = result.source_url.split("/api/v1/assets/", 1)[1].split("?", 1)[0]
    markdown_object = result.markdown_url.split("/api/v1/assets/", 1)[1].split("?", 1)[0]
    assert (await object_store.read_bytes(source_object)).startswith(b"PK")
    assert b"MQTT" in await object_store.read_bytes(markdown_object)
    skipped = await ingestion.ingest_path(source)
    assert skipped.skipped
    assert skipped.source_url == result.source_url
    assert skipped.markdown_url == result.markdown_url
    rag = RagService(
        HeuristicQueryRewriter(),
        HeuristicHydeGenerator(),
        embedder,
        store,
        LexicalReranker(),
        ExtractiveAnswerGenerator(),
        traces,
        InMemoryCache(),
        sessions,
    )
    message_id, session_id, answer = await rag.answer("MQTT端口是多少？", [], "session")
    assert "1883" in answer.answer
    assert answer.citations[0].filename == "mqtt.md"
    assert answer.citations[0].source_url == result.source_url
    assert answer.timings_ms["hyde_generation"] >= 0
    history = await rag.get_session_history(session_id)
    assert [item["role"] for item in history] == ["user", "assistant"]
    feedback = await rag.feedback(message_id, -1, "需要更简洁")
    assert feedback.reason == "需要更简洁"

@pytest.mark.asyncio
async def test_conversation_bypasses_empty_knowledge_base(tmp_path: Path) -> None:
    embedder = DeterministicHashEmbedder(128)
    store = InMemoryVectorStore()
    traces = InMemoryTraceRepository()
    sessions = InMemorySessionStore()
    rag = RagService(
        HeuristicQueryRewriter(),
        HeuristicHydeGenerator(),
        embedder,
        store,
        LexicalReranker(),
        ExtractiveAnswerGenerator(),
        traces,
        InMemoryCache(),
        sessions,
    )

    message_id, session_id, answer = await rag.answer("你好", [], "conversation")

    assert message_id
    assert session_id == "conversation"
    assert answer.answer == "你好！有什么可以帮你？"
    assert answer.citations == []
    assert answer.timings_ms["direct_answer_route"] == 1.0
