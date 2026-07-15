from dataclasses import asdict

from app.api.dependencies import enforce_chat_rate_limit, require_permission
from app.core.container import get_container
from app.schemas.chat import ChatRequest, ChatResponse, CitationResponse, SessionHistoryResponse
from fastapi import APIRouter, Depends, Request, Response
from rag_core.security import Permission, SecurityPrincipal

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, dependencies=[Depends(enforce_chat_rate_limit)])
async def chat(
    request: ChatRequest,
    response: Response,
    http_request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.CHAT_USE)),
) -> ChatResponse:
    message_id, session_id, answer = await get_container().rag.answer(
        request.query,
        [item.model_dump() for item in request.history],
        request.session_id,
        principal.tenant_id,
        principal.user_id,
    )
    await get_container().security.audit(
        principal,
        "chat.answer",
        "message",
        message_id,
        ip_address=_ip(http_request),
        user_agent=http_request.headers.get("user-agent", ""),
        request_id=http_request.state.request_id,
        details={"session_id": session_id, "citation_count": len(answer.citations)},
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
async def session_history(
    session_id: str,
    principal: SecurityPrincipal = Depends(require_permission(Permission.SESSION_READ)),
) -> SessionHistoryResponse:
    history = await get_container().rag.get_session_history(
        session_id, principal.tenant_id, principal.user_id
    )
    return SessionHistoryResponse(session_id=session_id, history=history)


@router.delete("/sessions/{session_id}", status_code=204)
async def clear_session(
    session_id: str,
    request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.SESSION_DELETE)),
) -> Response:
    await get_container().rag.clear_session(session_id, principal.tenant_id, principal.user_id)
    await get_container().security.audit(
        principal,
        "session.delete",
        "session",
        session_id,
        ip_address=_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        request_id=request.state.request_id,
    )
    return Response(status_code=204)


def _ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
