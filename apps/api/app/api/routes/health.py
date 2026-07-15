from app.core.config import get_settings
from app.schemas.common import HealthResponse
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok", environment=settings.app_env, use_mocks=settings.rag_use_mocks
    )
