from __future__ import annotations

import math
from collections.abc import Sequence

from rag_core.models import DocumentChunk, Feedback, MessageTrace, VectorHit


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

    async def delete_document(self, document_id: str) -> None:
        for chunk_id in [
            key for key, value in self.records.items() if value[0].document_id == document_id
        ]:
            del self.records[chunk_id]

    async def search(self, embedding: Sequence[float], limit: int) -> list[VectorHit]:
        if self.dimension is None or len(embedding) != self.dimension:
            raise ValueError("Query embedding dimension does not match vector schema")
        hits = [
            VectorHit(chunk=chunk, score=_cosine(embedding, vector))
            for chunk, vector in self.records.values()
        ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    async def get_document_chunks(self, document_ids: Sequence[str]) -> list[DocumentChunk]:
        wanted = set(document_ids)
        chunks = [chunk for chunk, _ in self.records.values() if chunk.document_id in wanted]
        return sorted(chunks, key=lambda chunk: (chunk.document_id, chunk.chunk_index))

    async def count(self) -> int:
        return len(self.records)


class InMemoryTraceRepository:
    def __init__(self) -> None:
        self.messages: dict[str, MessageTrace] = {}
        self.feedback: dict[str, Feedback] = {}

    async def save_message(self, trace: MessageTrace) -> None:
        self.messages[trace.message_id] = trace

    async def save_feedback(self, feedback: Feedback) -> None:
        if feedback.message_id not in self.messages:
            raise KeyError(f"Message not found: {feedback.message_id}")
        self.feedback[feedback.feedback_id] = feedback

    async def get_message(self, message_id: str) -> MessageTrace | None:
        return self.messages.get(message_id)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return dot / (left_norm * right_norm)
