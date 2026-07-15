from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol

from rag_core.models import (
    Document,
    DocumentChunk,
    Feedback,
    GeneratedAnswer,
    MessageTrace,
    RetrievalResult,
    SemanticMetadata,
    VectorHit,
)


class DocumentParser(Protocol):
    def supports(self, path: Path) -> bool: ...
    def parse(self, path: Path) -> Document: ...


class DocumentCleaner(Protocol):
    def clean(self, document: Document) -> Document: ...


class DocumentExporter(Protocol):
    def export(self, document: Document, output_dir: Path) -> tuple[Path, Path]: ...


class MetadataEnricher(Protocol):
    async def enrich(self, document: Document) -> SemanticMetadata: ...


class Chunker(Protocol):
    def split(self, document: Document) -> list[DocumentChunk]: ...


class Embedder(Protocol):
    dimension: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    async def ensure_schema(self, embedding_dimension: int) -> None: ...
    async def upsert(
        self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]
    ) -> None: ...
    async def delete_document(self, document_id: str, tenant_id: str = "default") -> None: ...
    async def search(
        self, embedding: Sequence[float], limit: int, tenant_id: str = "default"
    ) -> list[VectorHit]: ...
    async def get_document_chunks(
        self, document_ids: Sequence[str], tenant_id: str = "default"
    ) -> list[DocumentChunk]: ...
    async def count(self, tenant_id: str = "default") -> int: ...


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: Sequence[RetrievalResult]
    ) -> list[RetrievalResult]: ...


class QueryRewriter(Protocol):
    async def rewrite(self, query: str, history: Sequence[dict[str, str]]) -> str: ...


class HydeGenerator(Protocol):
    async def generate(self, query: str) -> str: ...


class SessionStore(Protocol):
    async def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]: ...
    async def append_message(
        self, session_id: str, role: str, content: str, ttl_seconds: int = 86400
    ) -> None: ...
    async def clear(self, session_id: str) -> None: ...


class RateLimiter(Protocol):
    async def check(self, key: str, limit: int, window_seconds: int) -> object: ...


class AnswerGenerator(Protocol):
    async def generate(
        self, query: str, contexts: Sequence[RetrievalResult]
    ) -> GeneratedAnswer: ...
    async def stream(
        self, query: str, contexts: Sequence[RetrievalResult]
    ) -> AsyncIterator[str]: ...


class ObjectStore(Protocol):
    async def upload(self, local_path: Path, object_name: str) -> str: ...
    def resolve_url(self, object_name: str) -> str: ...
    async def read_bytes(self, object_name: str) -> bytes: ...
    def verify_signature(self, object_name: str, signature: str) -> bool: ...


class Cache(Protocol):
    async def get_json(self, key: str) -> object | None: ...
    async def set_json(self, key: str, value: object, ttl_seconds: int = 300) -> None: ...


class TraceRepository(Protocol):
    async def save_message(self, trace: MessageTrace) -> None: ...
    async def save_feedback(self, feedback: Feedback) -> None: ...
    async def get_message(
        self, message_id: str, tenant_id: str = "default"
    ) -> MessageTrace | None: ...
