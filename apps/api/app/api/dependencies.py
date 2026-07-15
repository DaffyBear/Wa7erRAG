from __future__ import annotations

from collections.abc import Callable

from app.core.config import get_settings
from app.core.container import get_container
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from rag_core.security import Permission, SecurityPrincipal

bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def optional_principal(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Depends(api_key_scheme),
) -> SecurityPrincipal | None:
    settings = get_settings()
    if not settings.security_enabled:
        return SecurityPrincipal(
            "development-user",
            "default",
            "development",
            ("admin",),
            frozenset(Permission),
            "disabled",
        )
    try:
        if bearer:
            principal = await get_container().security.authenticate_token(bearer.credentials)
        elif api_key:
            principal = await get_container().security.authenticate_api_key(api_key)
        else:
            return None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    request.state.principal = principal
    return principal


async def current_principal(
    principal: SecurityPrincipal | None = Depends(optional_principal),
) -> SecurityPrincipal:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_permission(permission: Permission) -> Callable:
    async def dependency(
        principal: SecurityPrincipal = Depends(current_principal),
    ) -> SecurityPrincipal:
        if not principal.can(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission.value}",
            )
        return principal

    return dependency


async def enforce_chat_rate_limit(
    request: Request, response: Response, principal: SecurityPrincipal = Depends(current_principal)
) -> None:
    settings = get_settings()
    await _enforce(
        request,
        response,
        "chat",
        settings.rag_chat_rate_limit,
        settings.rag_rate_window_seconds,
        principal,
    )


async def enforce_upload_rate_limit(
    request: Request, response: Response, principal: SecurityPrincipal = Depends(current_principal)
) -> None:
    settings = get_settings()
    await _enforce(
        request,
        response,
        "upload",
        settings.rag_upload_rate_limit,
        settings.rag_rate_window_seconds,
        principal,
    )


async def _enforce(
    request: Request,
    response: Response,
    operation: str,
    limit: int,
    window_seconds: int,
    principal: SecurityPrincipal,
) -> None:
    result = await get_container().rate_limiter.check(
        f"{operation}:{principal.tenant_id}:{principal.user_id}", limit, window_seconds
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
