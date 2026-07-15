from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rag_core.contracts import (
    AnswerGenerator,
    Cache,
    Chunker,
    DocumentCleaner,
    DocumentExporter,
    Embedder,
    MetadataEnricher,
    ObjectStore,
    QueryRewriter,
    Reranker,
    TraceRepository,
    VectorStore,
)
from rag_core.generation import replace_asset_urls
from rag_core.metrics import FEEDBACK_COUNT, INGESTED_DOCUMENTS, STAGE_LATENCY
from rag_core.models import Citation, Feedback, GeneratedAnswer, IngestionResult, MessageTrace
from rag_core.retrieval import ParentDocumentRetriever
from rag_core.utils import atomic_json_write, read_json, stable_id


class IngestionService:
    def __init__(
        self,
        parser_registry: Any,
        cleaner: DocumentCleaner,
        exporter: DocumentExporter,
        enricher: MetadataEnricher,
        chunker: Chunker,
        embedder: Embedder,
        vector_store: VectorStore,
        object_store: ObjectStore,
        output_root: Path,
        checkpoint_path: Path,
        lock_manager: Any,
    ) -> None:
        self.parser_registry = parser_registry
        self.cleaner = cleaner
        self.exporter = exporter
        self.enricher = enricher
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.object_store = object_store
        self.output_root = output_root
        self.checkpoint_path = checkpoint_path
        self.lock_manager = lock_manager
        self.local_lock = asyncio.Lock()

    async def ingest_path(self, path: Path, force: bool = False) -> IngestionResult:
        lock_name = f"ingest:{stable_id(str(path.resolve()))}"
        async with self.lock_manager.lock(
            lock_name,
            ttl_seconds=900,
            wait_timeout_seconds=1.0,
        ):
            async with self.local_lock:
                checkpoints = read_json(self.checkpoint_path, {})
            document = self.cleaner.clean(self.parser_registry.parse(path))
            if not force and checkpoints.get(str(path.resolve())) == document.checksum:
                INGESTED_DOCUMENTS.labels(status="skipped").inc()
                return IngestionResult(document.document_id, document.filename, 0, skipped=True)
            with STAGE_LATENCY.labels(stage="enrichment").time():
                document.semantic = await self.enricher.enrich(document)
            asset_mapping: dict[str, str] = {}
            for asset in document.assets:
                local_path = Path(asset.local_path)
                object_name = f"{document.document_id}/{local_path.name}"
                asset.object_name = object_name
                asset.public_url = await self.object_store.upload(local_path, object_name)
                asset_mapping[asset.local_path] = asset.public_url
            document.content = replace_asset_urls(document.content, asset_mapping)
            markdown_path, docx_path = self.exporter.export(document, self.output_root)
            chunks = self.chunker.split(document)
            with STAGE_LATENCY.labels(stage="embedding").time():
                embeddings = await self.embedder.embed([chunk.embedding_text for chunk in chunks])
            await self.vector_store.ensure_schema(self.embedder.dimension)
            await self.vector_store.delete_document(document.document_id)
            await self.vector_store.upsert(chunks, embeddings)
            async with self.local_lock:
                checkpoints = read_json(self.checkpoint_path, {})
                checkpoints[str(path.resolve())] = document.checksum
                atomic_json_write(self.checkpoint_path, checkpoints)
            INGESTED_DOCUMENTS.labels(status="success").inc()
            return IngestionResult(
                document.document_id,
                document.filename,
                len(chunks),
                output_markdown=str(markdown_path),
                output_docx=str(docx_path),
            )

    async def ingest_directory(self, root: Path, force: bool = False) -> list[IngestionResult]:
        paths = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and self.parser_registry.supports(path)
        )
        results: list[IngestionResult] = []
        for path in paths:
            results.append(await self.ingest_path(path, force=force))
        return results


class RagService:
    def __init__(
        self,
        rewriter: QueryRewriter,
        hyde_generator: Any,
        embedder: Embedder,
        vector_store: VectorStore,
        reranker: Reranker,
        generator: AnswerGenerator,
        traces: TraceRepository,
        cache: Cache,
        session_store: Any,
        vector_top_k: int = 20,
        final_top_k: int = 5,
        cache_ttl_seconds: int = 300,
        session_ttl_seconds: int = 86400,
        hyde_enabled: bool = True,
    ) -> None:
        self.rewriter = rewriter
        self.hyde_generator = hyde_generator
        self.retriever = ParentDocumentRetriever(
            embedder,
            vector_store,
            reranker,
            vector_top_k,
            final_top_k,
        )
        self.generator = generator
        self.traces = traces
        self.cache = cache
        self.session_store = session_store
        self.cache_ttl_seconds = cache_ttl_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self.hyde_enabled = hyde_enabled

    async def answer(
        self,
        query: str,
        history: list[dict[str, str]],
        session_id: str | None = None,
    ) -> tuple[str, str, GeneratedAnswer]:
        actual_session_id = session_id or uuid.uuid4().hex
        stored_history = await self.session_store.get_history(actual_session_id, limit=20)
        effective_history = history or stored_history
        timings: dict[str, float] = {}

        started = time.perf_counter()
        rewritten = await self.rewriter.rewrite(query, effective_history)
        timings["rewrite"] = _elapsed(started)

        variants: list[str] = []
        if query.strip() != rewritten.strip():
            variants.append(query)
        if self.hyde_enabled:
            started = time.perf_counter()
            with STAGE_LATENCY.labels(stage="hyde_generation").time():
                hypothetical_answer = await self.hyde_generator.generate(rewritten)
            timings["hyde_generation"] = _elapsed(started)
            if hypothetical_answer:
                variants.append(hypothetical_answer)

        cache_key = f"rag:answer:{stable_id(rewritten, *variants)}"
        cached = await self.cache.get_json(cache_key)
        contexts = []
        if isinstance(cached, dict):
            generated = GeneratedAnswer(
                answer=str(cached["answer"]),
                rewritten_query=rewritten,
                citations=[Citation(**item) for item in cached.get("citations", [])],
            )
            timings["cache_hit"] = 1.0
        else:
            started = time.perf_counter()
            with STAGE_LATENCY.labels(stage="retrieval_rerank").time():
                contexts = await self.retriever.retrieve(rewritten, variants)
            timings["retrieval_rerank"] = _elapsed(started)
            started = time.perf_counter()
            with STAGE_LATENCY.labels(stage="generation").time():
                generated = await self.generator.generate(rewritten, contexts)
            timings["generation"] = _elapsed(started)
            await self.cache.set_json(
                cache_key,
                {
                    "answer": generated.answer,
                    "citations": [asdict(item) for item in generated.citations],
                },
                self.cache_ttl_seconds,
            )

        generated.rewritten_query = rewritten
        generated.timings_ms = timings | {"total": round(sum(timings.values()), 3)}
        message_id = uuid.uuid4().hex
        retrieved_documents = (
            [
                {
                    "document_id": item.document_id,
                    "filename": item.filename,
                    "score": item.score,
                    "matched_routes": item.metadata.get("matched_routes", []),
                    "rrf_score": item.metadata.get("rrf_score", 0.0),
                }
                for item in contexts
            ]
            if contexts
            else [asdict(item) for item in generated.citations]
        )
        trace = MessageTrace(
            message_id=message_id,
            session_id=actual_session_id,
            query=query,
            rewritten_query=rewritten,
            answer=generated.answer,
            retrieved_documents=retrieved_documents,
            timings_ms=generated.timings_ms,
        )
        await self.traces.save_message(trace)
        await self.session_store.append_message(
            actual_session_id,
            "user",
            query,
            self.session_ttl_seconds,
        )
        await self.session_store.append_message(
            actual_session_id,
            "assistant",
            generated.answer,
            self.session_ttl_seconds,
        )
        return message_id, actual_session_id, generated

    async def get_session_history(self, session_id: str) -> list[dict[str, str]]:
        return await self.session_store.get_history(session_id, limit=100)

    async def clear_session(self, session_id: str) -> None:
        await self.session_store.clear(session_id)

    async def feedback(self, message_id: str, value: int, reason: str = "") -> Feedback:
        if value not in (-1, 1):
            raise ValueError("feedback value must be -1 or 1")
        feedback = Feedback(uuid.uuid4().hex, message_id, value, reason)
        await self.traces.save_feedback(feedback)
        FEEDBACK_COUNT.labels(value=str(value)).inc()
        return feedback


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
