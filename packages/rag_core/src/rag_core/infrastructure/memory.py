from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from rag_core.models import ChatSession, DocumentChunk, Feedback, MessageTrace, VectorHit


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.dimension: int | None = None
        self.records: dict[str, tuple[DocumentChunk, list[float]]] = {}

    async def ensure_schema(self, embedding_dimension: int) -> None:
        if self.dimension is not None and self.dimension != embedding_dimension:
            raise ValueError(
                f"Vector schema dimension is {self.dimension}, requested {embedding_dimension}"
            )
        self.dimension = embedding_dimension

    async def upsert(
        self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have identical lengths")
        if self.dimension is None:
            raise RuntimeError("ensure_schema must be called before upsert")
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            if len(embedding) != self.dimension:
                raise ValueError(f"Embedding dimension mismatch, expected {self.dimension}")
            self.records[chunk.chunk_id] = (chunk, list(embedding))

    async def delete_document(self, document_id: str, tenant_id: str = "default") -> None:
        for chunk_id in [
            key
            for key, value in self.records.items()
            if value[0].document_id == document_id
            and value[0].metadata.get("tenant_id", "default") == tenant_id
        ]:
            del self.records[chunk_id]

    async def search(
        self, embedding: Sequence[float], limit: int, tenant_id: str = "default"
    ) -> list[VectorHit]:
        if self.dimension is None or len(embedding) != self.dimension:
            raise ValueError("Query embedding dimension does not match vector schema")
        hits = [
            VectorHit(chunk=chunk, score=_cosine(embedding, vector))
            for chunk, vector in self.records.values()
            if chunk.metadata.get("tenant_id", "default") == tenant_id
        ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    async def lexical_search(
        self, query: str, limit: int, tenant_id: str = "default"
    ) -> list[VectorHit]:
        records = [
            chunk
            for chunk, _ in self.records.values()
            if chunk.metadata.get("tenant_id", "default") == tenant_id
        ]
        query_terms = _bm25_terms(query)
        if not records or not query_terms:
            return []
        tokenized = [_bm25_terms(chunk.content) for chunk in records]
        average_length = sum(len(terms) for terms in tokenized) / len(tokenized) or 1.0
        document_frequency = Counter(
            term for terms in tokenized for term in set(terms)
        )
        hits: list[VectorHit] = []
        for chunk, terms in zip(records, tokenized, strict=True):
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                inverse_frequency = math.log(
                    1.0
                    + (len(records) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                denominator = frequency + 1.5 * (
                    1.0 - 0.75 + 0.75 * len(terms) / average_length
                )
                score += inverse_frequency * frequency * 2.5 / denominator
            if score > 0:
                hits.append(VectorHit(chunk=chunk, score=score))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    async def get_document_chunks(
        self, document_ids: Sequence[str], tenant_id: str = "default"
    ) -> list[DocumentChunk]:
        wanted = set(document_ids)
        chunks = [
            chunk
            for chunk, _ in self.records.values()
            if chunk.document_id in wanted
            and chunk.metadata.get("tenant_id", "default") == tenant_id
        ]
        return sorted(chunks, key=lambda chunk: (chunk.document_id, chunk.chunk_index))

    async def count(self, tenant_id: str = "default") -> int:
        return sum(
            1
            for chunk, _ in self.records.values()
            if chunk.metadata.get("tenant_id", "default") == tenant_id
        )


class InMemoryTraceRepository:
    def __init__(self) -> None:
        self.messages: dict[str, MessageTrace] = {}
        self.feedback: dict[str, Feedback] = {}
        self.session_titles: dict[tuple[str, str, str], str] = {}

    async def save_message(self, trace: MessageTrace) -> None:
        self.messages[trace.message_id] = trace

    async def save_feedback(self, feedback: Feedback) -> None:
        if (
            feedback.message_id not in self.messages
            or self.messages[feedback.message_id].tenant_id != feedback.tenant_id
        ):
            raise KeyError(f"Message not found: {feedback.message_id}")
        self.feedback[feedback.feedback_id] = feedback

    async def get_message(self, message_id: str, tenant_id: str = "default") -> MessageTrace | None:
        trace = self.messages.get(message_id)
        return trace if trace and trace.tenant_id == tenant_id else None

    async def list_sessions(
        self, tenant_id: str, user_id: str, limit: int = 100
    ) -> list[ChatSession]:
        grouped: dict[str, list[MessageTrace]] = {}
        for trace in self.messages.values():
            if trace.tenant_id == tenant_id and trace.user_id == user_id:
                grouped.setdefault(trace.session_id, []).append(trace)
        sessions = [self._session_from_messages(items) for items in grouped.values()]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)[:limit]

    async def get_session_messages(
        self, session_id: str, tenant_id: str, user_id: str
    ) -> list[MessageTrace]:
        return sorted(
            [
                trace
                for trace in self.messages.values()
                if trace.session_id == session_id
                and trace.tenant_id == tenant_id
                and trace.user_id == user_id
            ],
            key=lambda item: item.created_at,
        )

    async def rename_session(
        self, session_id: str, title: str, tenant_id: str, user_id: str
    ) -> ChatSession | None:
        messages = await self.get_session_messages(session_id, tenant_id, user_id)
        if not messages:
            return None
        self.session_titles[(session_id, tenant_id, user_id)] = title
        return self._session_from_messages(messages)

    async def delete_session(self, session_id: str, tenant_id: str, user_id: str) -> bool:
        message_ids = [
            message_id
            for message_id, trace in self.messages.items()
            if trace.session_id == session_id
            and trace.tenant_id == tenant_id
            and trace.user_id == user_id
        ]
        for message_id in message_ids:
            del self.messages[message_id]
        self.session_titles.pop((session_id, tenant_id, user_id), None)
        return bool(message_ids)

    def _session_from_messages(self, messages: list[MessageTrace]) -> ChatSession:
        ordered = sorted(messages, key=lambda item: item.created_at)
        first = ordered[0]
        title = self.session_titles.get(
            (first.session_id, first.tenant_id, first.user_id),
            " ".join(first.query.split())[:80] or "New chat",
        )
        return ChatSession(
            session_id=first.session_id,
            title=title,
            message_count=len(ordered),
            tenant_id=first.tenant_id,
            user_id=first.user_id,
            created_at=first.created_at,
            updated_at=ordered[-1].created_at,
        )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return dot / (left_norm * right_norm)


def _bm25_terms(text: str) -> list[str]:
    normalized = text.lower()
    words = re.findall(r"[a-z0-9_.+-]+", normalized)
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    bigrams = [
        "".join(chinese[index : index + 2])
        for index in range(max(len(chinese) - 1, 0))
    ]
    return words + chinese + bigrams
