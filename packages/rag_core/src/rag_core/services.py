from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
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
    RetrievalRouter,
    TraceRepository,
    VectorStore,
)
from rag_core.generation import citations_from_answer, replace_asset_urls
from rag_core.metrics import FEEDBACK_COUNT, INGESTED_DOCUMENTS, STAGE_LATENCY
from rag_core.models import (
    ChatSession,
    Citation,
    Feedback,
    GeneratedAnswer,
    IngestionResult,
    MessageTrace,
)
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

    async def ingest_path(
        self, path: Path, force: bool = False, tenant_id: str = "default"
    ) -> IngestionResult:
        lock_name = f"ingest:{tenant_id}:{stable_id(str(path.resolve()))}"
        async with self.lock_manager.lock(
            lock_name,
            ttl_seconds=900,
            wait_timeout_seconds=1.0,
        ):
            async with self.local_lock:
                checkpoints = read_json(self.checkpoint_path, {})
            document = self.cleaner.clean(self.parser_registry.parse(path))
            document.document_id = stable_id(tenant_id, document.document_id)
            document.metadata["tenant_id"] = tenant_id
            if not force and checkpoints.get(f"{tenant_id}:{path.resolve()}") == document.checksum:
                document_dir = self.output_root / document.document_id
                document_stem = Path(document.filename).stem
                markdown_path = document_dir / f"{document_stem}.md"
                docx_path = document_dir / f"{document_stem}.docx"
                document_object_root = f"{tenant_id}/{document.document_id}/documents"
                INGESTED_DOCUMENTS.labels(status="skipped").inc()
                return IngestionResult(
                    document.document_id,
                    document.filename,
                    0,
                    skipped=True,
                    output_markdown=str(markdown_path),
                    output_docx=str(docx_path),
                    source_url=self.object_store.resolve_url(
                        f"{document_object_root}/{docx_path.name}"
                    ),
                    markdown_url=self.object_store.resolve_url(
                        f"{document_object_root}/{markdown_path.name}"
                    ),
                )
            with STAGE_LATENCY.labels(stage="enrichment").time():
                document.semantic = await self.enricher.enrich(document)
            asset_mapping: dict[str, str] = {}
            for asset in document.assets:
                local_path = Path(asset.local_path)
                object_name = f"{tenant_id}/{document.document_id}/{local_path.name}"
                asset.object_name = object_name
                asset.public_url = await self.object_store.upload(local_path, object_name)
                asset_mapping[asset.local_path] = asset.public_url
            markdown_path, docx_path = self.exporter.export(document, self.output_root)
            document_object_root = f"{tenant_id}/{document.document_id}/documents"
            source_url = await self.object_store.upload(
                docx_path, f"{document_object_root}/{docx_path.name}"
            )
            markdown_url = await self.object_store.upload(
                markdown_path, f"{document_object_root}/{markdown_path.name}"
            )
            document.metadata["source_url"] = source_url
            document.metadata["markdown_url"] = markdown_url
            document.content = replace_asset_urls(document.content, asset_mapping)
            chunks = self.chunker.split(document)
            with STAGE_LATENCY.labels(stage="embedding").time():
                embeddings = await self.embedder.embed([chunk.embedding_text for chunk in chunks])
            await self.vector_store.ensure_schema(self.embedder.dimension)
            await self.vector_store.delete_document(document.document_id, tenant_id)
            await self.vector_store.upsert(chunks, embeddings)
            async with self.local_lock:
                checkpoints = read_json(self.checkpoint_path, {})
                checkpoints[f"{tenant_id}:{path.resolve()}"] = document.checksum
                atomic_json_write(self.checkpoint_path, checkpoints)
            INGESTED_DOCUMENTS.labels(status="success").inc()
            return IngestionResult(
                document.document_id,
                document.filename,
                len(chunks),
                output_markdown=str(markdown_path),
                output_docx=str(docx_path),
                source_url=source_url,
                markdown_url=markdown_url,
            )

    async def ingest_directory(
        self, root: Path, force: bool = False, tenant_id: str = "default"
    ) -> list[IngestionResult]:
        paths = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and self.parser_registry.supports(path)
        )
        results: list[IngestionResult] = []
        for path in paths:
            results.append(await self.ingest_path(path, force=force, tenant_id=tenant_id))
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
        retrieval_router: RetrievalRouter | None = None,
        vector_top_k: int = 20,
        lexical_top_k: int = 20,
        hybrid_search_enabled: bool = True,
        rerank_candidate_count: int = 20,
        final_top_k: int = 5,
        cache_ttl_seconds: int = 300,
        session_ttl_seconds: int = 86400,
        hyde_enabled: bool = True,
    ) -> None:
        self.rewriter = rewriter
        self.retrieval_router = retrieval_router
        self.hyde_generator = hyde_generator
        self.retriever = ParentDocumentRetriever(
            embedder,
            vector_store,
            reranker,
            vector_top_k=vector_top_k,
            rerank_candidate_count=rerank_candidate_count,
            final_top_k=final_top_k,
            lexical_top_k=lexical_top_k,
            hybrid_enabled=hybrid_search_enabled,
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
        tenant_id: str = "default",
        user_id: str = "system",
    ) -> tuple[str, str, GeneratedAnswer]:
        actual_session_id = session_id or uuid.uuid4().hex
        scoped_session_id = f"{tenant_id}:{user_id}:{actual_session_id}"
        stored_history = await self.session_store.get_history(scoped_session_id, limit=20)
        effective_history = history or stored_history
        timings: dict[str, float] = {}

        use_retrieval = await self._route_retrieval(query, effective_history, timings)
        if use_retrieval and await self.retriever.vector_store.count(tenant_id) == 0:
            use_retrieval = False
        rewritten = query.strip()
        variants: list[str] = []
        lexical_variants: list[str] = []
        if use_retrieval:
            started = time.perf_counter()
            try:
                rewritten = await self.rewriter.rewrite(query, effective_history)
            except Exception:
                rewritten = query.strip()
                timings["rewrite_fallback"] = _elapsed(started)
            else:
                timings["rewrite"] = _elapsed(started)
                if query.strip() != rewritten.strip():
                    variants.append(query)
                    lexical_variants.append(query)
            if self.hyde_enabled and _should_run_hyde(rewritten):
                started = time.perf_counter()
                try:
                    with STAGE_LATENCY.labels(stage="hyde_generation").time():
                        hypothetical_answer = await self.hyde_generator.generate(rewritten)
                except Exception:
                    timings["hyde_fallback"] = _elapsed(started)
                else:
                    timings["hyde_generation"] = _elapsed(started)
                    if hypothetical_answer:
                        variants.append(hypothetical_answer)
        else:
            timings["direct_answer_route"] = 1.0

        route = "rag" if use_retrieval else "direct"
        cache_key = f"rag:answer:hybrid-v2:{route}:{tenant_id}:{stable_id(rewritten, *variants)}"
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
            if use_retrieval:
                started = time.perf_counter()
                with STAGE_LATENCY.labels(stage="retrieval_rerank").time():
                    contexts = await self.retriever.retrieve(
                        rewritten,
                        variants,
                        tenant_id,
                        lexical_variants=lexical_variants,
                    )
                timings["retrieval_rerank"] = _elapsed(started)
            started = time.perf_counter()
            with STAGE_LATENCY.labels(stage="generation").time():
                generated = await self.generator.generate(rewritten, contexts, effective_history)
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
                    "source_url": item.metadata.get("source_url"),
                    "matched_routes": item.metadata.get("matched_routes", []),
                    "rrf_score": item.metadata.get("rrf_score", 0.0),
                    "rerank_provider": item.metadata.get("rerank_provider", ""),
                    "rerank_model": item.metadata.get("rerank_model", ""),
                    "rerank_fallback_reason": item.metadata.get("rerank_fallback_reason", ""),
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
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await self.traces.save_message(trace)
        await self.session_store.append_message(
            scoped_session_id,
            "user",
            query,
            self.session_ttl_seconds,
        )
        await self.session_store.append_message(
            scoped_session_id,
            "assistant",
            generated.answer,
            self.session_ttl_seconds,
        )
        return message_id, actual_session_id, generated

    async def stream_answer(
        self,
        query: str,
        history: list[dict[str, str]],
        session_id: str | None = None,
        tenant_id: str = "default",
        user_id: str = "system",
    ) -> AsyncIterator[dict[str, Any]]:
        actual_session_id = session_id or uuid.uuid4().hex
        scoped_session_id = f"{tenant_id}:{user_id}:{actual_session_id}"
        stored_history = await self.session_store.get_history(scoped_session_id, limit=20)
        effective_history = history or stored_history
        timings: dict[str, float] = {}

        use_retrieval = await self._route_retrieval(query, effective_history, timings)
        if use_retrieval and await self.retriever.vector_store.count(tenant_id) == 0:
            use_retrieval = False
        rewritten = query.strip()
        variants: list[str] = []
        lexical_variants: list[str] = []
        yield {
            "type": "start",
            "session_id": actual_session_id,
            "rewritten_query": rewritten,
            "use_retrieval": use_retrieval,
            "hyde_enabled": self.hyde_enabled,
        }

        if use_retrieval:
            started = time.perf_counter()
            try:
                rewrite_parts: list[str] = []
                stream_rewrite = getattr(self.rewriter, "stream", None)
                if callable(stream_rewrite):
                    async for content in stream_rewrite(query, effective_history):
                        rewrite_parts.append(content)
                        yield {"type": "rewrite_delta", "content": content}
                    rewritten = "".join(rewrite_parts).strip() or query.strip()
                else:
                    rewritten = await self.rewriter.rewrite(query, effective_history)
            except Exception:
                rewritten = query.strip()
                rewrite_stage = "rewrite_fallback"
            else:
                rewrite_stage = "rewrite"
                if query.strip() != rewritten.strip():
                    variants.append(query)
                    lexical_variants.append(query)
            timings[rewrite_stage] = _elapsed(started)
            yield {
                "type": "timing",
                "stage": rewrite_stage,
                "duration_ms": timings[rewrite_stage],
            }
            yield {"type": "rewrite", "rewritten_query": rewritten}

            if self.hyde_enabled and _should_run_hyde(rewritten):
                started = time.perf_counter()
                try:
                    with STAGE_LATENCY.labels(stage="hyde_generation").time():
                        hypothetical_answer = await self.hyde_generator.generate(rewritten)
                except Exception:
                    hyde_stage = "hyde_fallback"
                else:
                    hyde_stage = "hyde_generation"
                    if hypothetical_answer:
                        variants.append(hypothetical_answer)
                timings[hyde_stage] = _elapsed(started)
                yield {
                    "type": "timing",
                    "stage": hyde_stage,
                    "duration_ms": timings[hyde_stage],
                }
        else:
            timings["direct_answer_route"] = 1.0
            yield {
                "type": "timing",
                "stage": "direct_answer_route",
                "duration_ms": timings["direct_answer_route"],
            }

        route = "rag" if use_retrieval else "direct"
        cache_key = f"rag:answer:hybrid-v2:{route}:{tenant_id}:{stable_id(rewritten, *variants)}"
        cached = await self.cache.get_json(cache_key)
        contexts = []

        if isinstance(cached, dict):
            answer_text = str(cached["answer"])
            citations = [Citation(**item) for item in cached.get("citations", [])]
            timings["cache_hit"] = 1.0
            yield {
                "type": "timing",
                "stage": "cache_hit",
                "duration_ms": timings["cache_hit"],
            }
            if answer_text:
                yield {"type": "delta", "content": answer_text}
        else:
            if use_retrieval:
                started = time.perf_counter()
                with STAGE_LATENCY.labels(stage="retrieval_rerank").time():
                    contexts = await self.retriever.retrieve(
                        rewritten,
                        variants,
                        tenant_id,
                        lexical_variants=lexical_variants,
                    )
                timings["retrieval_rerank"] = _elapsed(started)
                yield {
                    "type": "timing",
                    "stage": "retrieval_rerank",
                    "duration_ms": timings["retrieval_rerank"],
                }

            started = time.perf_counter()
            first_token_recorded = False
            answer_parts: list[str] = []
            with STAGE_LATENCY.labels(stage="generation").time():
                async for content in self.generator.stream(rewritten, contexts, effective_history):
                    if not first_token_recorded:
                        timings["first_token"] = _elapsed(started)
                        first_token_recorded = True
                        yield {
                            "type": "timing",
                            "stage": "first_token",
                            "duration_ms": timings["first_token"],
                        }
                    answer_parts.append(content)
                    yield {"type": "delta", "content": content}
            timings["generation"] = _elapsed(started)
            yield {
                "type": "timing",
                "stage": "generation",
                "duration_ms": timings["generation"],
            }
            answer_text = "".join(answer_parts)
            citations = citations_from_answer(answer_text, contexts)
            await self.cache.set_json(
                cache_key,
                {
                    "answer": answer_text,
                    "citations": [asdict(item) for item in citations],
                },
                self.cache_ttl_seconds,
            )

        timings["total"] = round(
            sum(value for stage, value in timings.items() if stage != "first_token"), 3
        )
        yield {
            "type": "timing",
            "stage": "total",
            "duration_ms": timings["total"],
        }
        message_id = uuid.uuid4().hex
        retrieved_documents = (
            [
                {
                    "document_id": item.document_id,
                    "filename": item.filename,
                    "score": item.score,
                    "source_url": item.metadata.get("source_url"),
                    "matched_routes": item.metadata.get("matched_routes", []),
                    "rrf_score": item.metadata.get("rrf_score", 0.0),
                    "rerank_provider": item.metadata.get("rerank_provider", ""),
                    "rerank_model": item.metadata.get("rerank_model", ""),
                    "rerank_fallback_reason": item.metadata.get("rerank_fallback_reason", ""),
                }
                for item in contexts
            ]
            if contexts
            else [asdict(item) for item in citations]
        )
        await self.traces.save_message(
            MessageTrace(
                message_id=message_id,
                session_id=actual_session_id,
                query=query,
                rewritten_query=rewritten,
                answer=answer_text,
                retrieved_documents=retrieved_documents,
                timings_ms=timings,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        )
        await self.session_store.append_message(
            scoped_session_id, "user", query, self.session_ttl_seconds
        )
        await self.session_store.append_message(
            scoped_session_id, "assistant", answer_text, self.session_ttl_seconds
        )
        yield {
            "type": "done",
            "message_id": message_id,
            "session_id": actual_session_id,
            "rewritten_query": rewritten,
            "citations": [asdict(item) for item in citations],
            "timings_ms": timings,
        }

    async def _route_retrieval(
        self,
        query: str,
        history: list[dict[str, str]],
        timings: dict[str, float],
    ) -> bool:
        if self.retrieval_router is None:
            return _should_use_retrieval(query)
        started = time.perf_counter()
        try:
            with STAGE_LATENCY.labels(stage="retrieval_router").time():
                decision = await self.retrieval_router.decide(query, history)
        except Exception:
            timings["retrieval_router_fallback"] = _elapsed(started)
            return True
        timings["retrieval_router"] = _elapsed(started)
        return decision.needs_retrieval

    async def list_sessions(
        self, tenant_id: str = "default", user_id: str = "system", limit: int = 100
    ) -> list[ChatSession]:
        return await self.traces.list_sessions(tenant_id, user_id, limit)

    async def get_session_messages(
        self, session_id: str, tenant_id: str = "default", user_id: str = "system"
    ) -> list[MessageTrace]:
        return await self.traces.get_session_messages(session_id, tenant_id, user_id)

    async def get_session_history(
        self, session_id: str, tenant_id: str = "default", user_id: str = "system"
    ) -> list[dict[str, str]]:
        messages = await self.get_session_messages(session_id, tenant_id, user_id)
        if messages:
            history: list[dict[str, str]] = []
            for message in messages:
                history.extend(
                    [
                        {"role": "user", "content": message.query},
                        {"role": "assistant", "content": message.answer},
                    ]
                )
            return history
        return await self.session_store.get_history(
            f"{tenant_id}:{user_id}:{session_id}", limit=100
        )

    async def rename_session(
        self,
        session_id: str,
        title: str,
        tenant_id: str = "default",
        user_id: str = "system",
    ) -> ChatSession | None:
        return await self.traces.rename_session(session_id, title, tenant_id, user_id)

    async def clear_session(
        self, session_id: str, tenant_id: str = "default", user_id: str = "system"
    ) -> bool:
        await self.session_store.clear(f"{tenant_id}:{user_id}:{session_id}")
        return await self.traces.delete_session(session_id, tenant_id, user_id)

    async def feedback(
        self,
        message_id: str,
        value: int,
        reason: str = "",
        tenant_id: str = "default",
        user_id: str = "system",
    ) -> Feedback:
        if value not in (-1, 1):
            raise ValueError("feedback value must be -1 or 1")
        if await self.traces.get_message(message_id, tenant_id) is None:
            raise KeyError(f"Message not found: {message_id}")
        feedback = Feedback(uuid.uuid4().hex, message_id, value, reason, tenant_id, user_id)
        await self.traces.save_feedback(feedback)
        FEEDBACK_COUNT.labels(value=str(value)).inc()
        return feedback


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _should_run_hyde(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    cjk_count = len([character for character in normalized if "\u4e00" <= character <= "\u9fff"])
    if cjk_count:
        return cjk_count >= 20
    word_count = len(normalized.split())
    return word_count >= 25


def _should_use_retrieval(query: str) -> bool:
    normalized = "".join(query.strip().lower().split())
    model_metadata_markers = (
        "你是什么模型",
        "你用的什么模型",
        "你的模型是什么",
        "你的模型版本",
        "当前模型是什么",
        "模型名称是什么",
        "知识截止时间",
        "知识更新到什么时候",
        "知识库时间到哪",
        "知识库更新到什么时候",
        "训练数据截止",
        "knowledgecutoff",
        "whatmodelareyou",
        "whichmodelareyou",
    )
    if any(marker in normalized for marker in model_metadata_markers):
        return False
    conversational = {
        "你好",
        "您好",
        "嗨",
        "hi",
        "hello",
        "在吗",
        "谢谢",
        "感谢",
        "再见",
        "拜拜",
        "你是谁",
        "你能做什么",
        "介绍一下你自己",
    }
    if normalized in conversational:
        return False
    return len(normalized) > 2
