from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)


class CitationResponse(BaseModel):
    document_id: str
    filename: str
    score: float
    source_url: str | None = None


class ChatResponse(BaseModel):
    message_id: str
    session_id: str
    answer: str
    rewritten_query: str
    citations: list[CitationResponse]
    timings_ms: dict[str, float]


class SessionSummaryResponse(BaseModel):
    session_id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionSummaryResponse]


class SessionMessageResponse(BaseModel):
    message_id: str
    query: str
    answer: str
    rewritten_query: str
    citations: list[CitationResponse]
    timings_ms: dict[str, float]
    created_at: datetime


class SessionDetailResponse(BaseModel):
    session_id: str
    title: str
    messages: list[SessionMessageResponse]


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class SessionHistoryResponse(BaseModel):
    session_id: str
    history: list[ChatMessage]