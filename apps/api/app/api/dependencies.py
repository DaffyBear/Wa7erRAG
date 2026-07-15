from __future__ import annotations

from app.core.config import get_settings
from app.core.container import get_container
from fastapi import HTTPException, Request, Response, status


async def enforce_chat_rate_limit(request: Request, response: Response) -> None:
    settings = get_settings()
    await _enforce(
        request=request,
        response=response,
        operation="chat",
        limit=settings.rag_chat_rate_limit,
        window_seconds=settings.rag_rate_window_seconds,
    )


async def enforce_upload_rate_limit(request: Request, response: Response) -> None:
    settings = get_settings()
    await _enforce(
        request=request,
        response=response,
        operation="upload",
        limit=settings.rag_upload_rate_limit,
        window_seconds=settings.rag_rate_window_seconds,
    )


async def _enforce(
    request: Request,
    response: Response,
    operation: str,
    limit: int,
    window_seconds: int,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    client_ip = forwarded or (request.client.host if request.client else "unknown")
    subject = request.headers.get("x-user-id") or client_ip
    result = await get_container().rate_limiter.check(
        f"{operation}:{subject}",
        limit,
        window_seconds,
    )
    request.state.rate_limit_remaining = result.remaining
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={
                "Retry-After": str(result.retry_after_seconds),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
