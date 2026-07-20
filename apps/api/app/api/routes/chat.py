import json
from dataclasses import asdict

from app.api.dependencies import enforce_chat_rate_limit, require_permission
from app.core.container import get_container
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    CitationResponse,
    SessionDetailResponse,
    SessionHistoryResponse,
    SessionListResponse,
    SessionMessageResponse,
    SessionRenameRequest,
    SessionSummaryResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
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

@router.post("/stream", dependencies=[Depends(enforce_chat_rate_limit)])
async def stream_chat(
    request: ChatRequest,
    http_request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.CHAT_USE)),
) -> StreamingResponse:
    async def events():
        message_id = ""
        session_id = request.session_id or ""
        citation_count = 0
        try:
            async for event in get_container().rag.stream_answer(
                request.query,
                [item.model_dump() for item in request.history],
                request.session_id,
                principal.tenant_id,
                principal.user_id,
            ):
                if event["type"] == "done":
                    message_id = str(event["message_id"])
                    session_id = str(event["session_id"])
                    citation_count = len(event["citations"])
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": str(error)}, ensure_ascii=False
            ) + "\n"
            return
        await get_container().security.audit(
            principal,
            "chat.answer.stream",
            "message",
            message_id,
            ip_address=_ip(http_request),
            user_agent=http_request.headers.get("user-agent", ""),
            request_id=http_request.state.request_id,
            details={"session_id": session_id, "citation_count": citation_count},
        )

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    principal: SecurityPrincipal = Depends(require_permission(Permission.SESSION_READ)),
) -> SessionListResponse:
    sessions = await get_container().rag.list_sessions(principal.tenant_id, principal.user_id)
    return SessionListResponse(
        sessions=[
            SessionSummaryResponse(
                session_id=item.session_id,
                title=item.title,
                message_count=item.message_count,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in sessions
        ]
    )


@router.get("/sessions/{session_id}/detail", response_model=SessionDetailResponse)
async def session_detail(
    session_id: str,
    principal: SecurityPrincipal = Depends(require_permission(Permission.SESSION_READ)),
) -> SessionDetailResponse:
    sessions = await get_container().rag.list_sessions(principal.tenant_id, principal.user_id)
    selected = next((item for item in sessions if item.session_id == session_id), None)
    if selected is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    messages = await get_container().rag.get_session_messages(
        session_id, principal.tenant_id, principal.user_id
    )
    return SessionDetailResponse(
        session_id=session_id,
        title=selected.title,
        messages=[
            SessionMessageResponse(
                message_id=item.message_id,
                query=item.query,
                answer=item.answer,
                rewritten_query=item.rewritten_query,
                citations=[
                    CitationResponse(
                        document_id=str(citation.get("document_id", "")),
                        filename=str(citation.get("filename", "")),
                        score=float(citation.get("score", 0.0)),
                        source_url=citation.get("source_url"),
                    )
                    for citation in item.retrieved_documents
                    if citation.get("document_id") and citation.get("filename")
                ],
                timings_ms=item.timings_ms,
                created_at=item.created_at,
            )
            for item in messages
        ],
    )


@router.patch("/sessions/{session_id}", response_model=SessionSummaryResponse)
async def rename_session(
    session_id: str,
    request: SessionRenameRequest,
    principal: SecurityPrincipal = Depends(require_permission(Permission.SESSION_DELETE)),
) -> SessionSummaryResponse:
    renamed = await get_container().rag.rename_session(
        session_id,
        request.title.strip(),
        principal.tenant_id,
        principal.user_id,
    )
    if renamed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return SessionSummaryResponse(
        session_id=renamed.session_id,
        title=renamed.title,
        message_count=renamed.message_count,
        created_at=renamed.created_at,
        updated_at=renamed.updated_at,
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
    deleted = await get_container().rag.clear_session(
        session_id, principal.tenant_id, principal.user_id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
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
