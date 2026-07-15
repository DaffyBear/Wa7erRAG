from dataclasses import asdict

from app.api.dependencies import require_permission
from app.core.container import get_container
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from fastapi import APIRouter, Depends, HTTPException, Request
from rag_core.security import Permission, SecurityPrincipal

router = APIRouter(prefix="/messages", tags=["feedback"])


@router.post("/{message_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    message_id: str,
    request: FeedbackRequest,
    http_request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.CHAT_USE)),
) -> FeedbackResponse:
    if request.value not in (-1, 1):
        raise HTTPException(status_code=422, detail="Feedback value must be -1 or 1")
    try:
        feedback = await get_container().rag.feedback(
            message_id, request.value, request.reason, principal.tenant_id, principal.user_id
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    await get_container().security.audit(
        principal,
        "feedback.create",
        "message",
        message_id,
        request_id=http_request.state.request_id,
        details={"value": request.value},
    )
    return FeedbackResponse(**asdict(feedback))
