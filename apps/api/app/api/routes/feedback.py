from dataclasses import asdict

from app.core.container import get_container
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/messages", tags=["feedback"])


@router.post("/{message_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(message_id: str, request: FeedbackRequest) -> FeedbackResponse:
    if request.value not in (-1, 1):
        raise HTTPException(status_code=422, detail="Feedback value must be -1 or 1")
    try:
        feedback = await get_container().rag.feedback(message_id, request.value, request.reason)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FeedbackResponse(**asdict(feedback))
