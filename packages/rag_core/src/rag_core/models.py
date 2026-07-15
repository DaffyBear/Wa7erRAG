from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class SemanticMetadata:
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    prompt_version: str = ""
    model: str = ""


@dataclass(slots=True)
class Asset:
    local_path: str
    object_name: str = ""
    public_url: str = ""
    content_type: str = "application/octet-stream"


@dataclass(slots=True)
class Document:
    document_id: str
    filename: str
    source_path: Path
    content: str
    title: str = ""
    category: str | None = None
    checksum: str = ""
    semantic: SemanticMetadata = field(default_factory=SemanticMetadata)
    assets: list[Asset] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentChunk:
    chunk_id: str
    document_id: str
    filename: str
    chunk_index: int
    content: str
    embedding_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VectorHit:
    chunk: DocumentChunk
    score: float


@dataclass(slots=True)
class RetrievalResult:
    document_id: str
    filename: str
    content: str
    score: float
    chunks: list[DocumentChunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Citation:
    document_id: str
    filename: str
    score: float
    source_url: str | None = None


@dataclass(slots=True)
class GeneratedAnswer:
    answer: str
    rewritten_query: str
    citations: list[Citation]
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class IngestionResult:
    document_id: str
    filename: str
    chunk_count: int
    skipped: bool = False
    output_markdown: str = ""
    output_docx: str = ""


@dataclass(slots=True)
class MessageTrace:
    message_id: str
    session_id: str
    query: str
    rewritten_query: str
    answer: str
    retrieved_documents: list[dict[str, Any]]
    timings_ms: dict[str, float]
    tenant_id: str = "default"
    user_id: str = "system"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Feedback:
    feedback_id: str
    message_id: str
    value: int
    reason: str = ""
    tenant_id: str = "default"
    user_id: str = "system"
    created_at: datetime = field(default_factory=utc_now)
