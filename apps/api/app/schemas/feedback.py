from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    value: int = Field(ge=-1, le=1)
    reason: str = Field(default="", max_length=2000)


class FeedbackResponse(BaseModel):
    feedback_id: str
    message_id: str
    value: int
    reason: str
