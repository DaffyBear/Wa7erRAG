from dataclasses import asdict

from app.api.dependencies import enforce_chat_rate_limit
from app.core.container import get_container
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    CitationResponse,
    SessionHistoryResponse,
)
from fastapi import APIRouter, Depends, Response

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[Depends(enforce_chat_rate_limit)],
)
async def chat(request: ChatRequest, response: Response) -> ChatResponse:
    message_id, session_id, answer = await get_container().rag.answer(
        request.query,
        [item.model_dump() for item in request.history],
        request.session_id,
    )
    return ChatResponse(
        message_id=message_id,
        session_id=session_id,
        answer=answer.answer,
        rewritten_query=answer.rewritten_query,
        citations=[CitationResponse(**asdict(citation)) for citation in answer.citations],
        timings_ms=answer.timings_ms,
    )


@router.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def session_history(session_id: str) -> SessionHistoryResponse:
    history = await get_container().rag.get_session_history(session_id)
    return SessionHistoryResponse(session_id=session_id, history=history)


@router.delete("/sessions/{session_id}", status_code=204)
async def clear_session(session_id: str) -> Response:
    await get_container().rag.clear_session(session_id)
    return Response(status_code=204)
