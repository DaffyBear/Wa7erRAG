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


class SessionHistoryResponse(BaseModel):
    session_id: str
    history: list[ChatMessage]
