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
    ingestion = IngestionService(
        default_parser_registry(tmp_path / "extracted"),
        RegexDocumentCleaner(),
        DualFormatExporter(),
        HeuristicMetadataEnricher(),
        RecursiveDocumentChunker(),
        embedder,
        store,
        LocalObjectStore(tmp_path / "assets"),
        tmp_path / "processed",
        tmp_path / "checkpoint.json",
        InMemoryLockManager(),
    )
    result = await ingestion.ingest_path(source)
    assert result.chunk_count == 1
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
    assert answer.timings_ms["hyde_generation"] >= 0
    history = await rag.get_session_history(session_id)
    assert [item["role"] for item in history] == ["user", "assistant"]
    feedback = await rag.feedback(message_id, -1, "需要更简洁")
    assert feedback.reason == "需要更简洁"
