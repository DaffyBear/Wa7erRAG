from dataclasses import asdict

from app.api.dependencies import current_principal, require_permission
from app.core.config import get_settings
from app.core.container import get_container
from app.schemas.security import (
    ApiKeyResponse,
    AuditEventResponse,
    BootstrapRequest,
    CreateApiKeyRequest,
    CreateUserRequest,
    LoginRequest,
    PrincipalResponse,
    TokenResponse,
    UserResponse,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from rag_core.security import Permission, SecurityPrincipal

router = APIRouter(prefix="/security", tags=["security"])


@router.post("/bootstrap", response_model=TokenResponse, status_code=201)
async def bootstrap(
    body: BootstrapRequest, request: Request, x_bootstrap_token: str = Header(default="")
) -> TokenResponse:
    settings = get_settings()
    if x_bootstrap_token != settings.security_bootstrap_token:
        raise HTTPException(status_code=403, detail="Invalid bootstrap token")
    try:
        user, tenant = await get_container().security.bootstrap(
            body.username, body.password, body.tenant_name, body.tenant_slug
        )
        token, principal = await get_container().security.authenticate_password(
            body.username, body.password, tenant.slug
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await _audit(request, principal, "security.bootstrap", "tenant", tenant.tenant_id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.security_access_token_ttl_seconds,
        tenant_id=tenant.tenant_id,
        user_id=user.user_id,
        roles=list(principal.roles),
    )


@router.post("/token", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    settings = get_settings()
    rate = await get_container().rate_limiter.check(
        f"auth:login:{_ip(request)}",
        settings.security_login_rate_limit,
        settings.security_login_rate_window_seconds,
    )
    if not rate.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts",
            headers={"Retry-After": str(rate.retry_after_seconds)},
        )
    try:
        token, principal = await get_container().security.authenticate_password(
            body.username, body.password, body.tenant_slug
        )
    except ValueError as error:
        tenant = await get_container().security.repository.get_tenant_by_slug(
            body.tenant_slug.strip().casefold()
        )
        await get_container().security.audit(
            None,
            "auth.login",
            "session",
            outcome="failure",
            ip_address=_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            request_id=request.state.request_id,
            details={"username": body.username},
            tenant_id=tenant.tenant_id if tenant else "",
        )
        raise HTTPException(status_code=401, detail="Invalid credentials") from error
    await _audit(request, principal, "auth.login", "session")
    return TokenResponse(
        access_token=token,
        expires_in=settings.security_access_token_ttl_seconds,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        roles=list(principal.roles),
    )


@router.get("/me", response_model=PrincipalResponse)
async def me(principal: SecurityPrincipal = Depends(current_principal)) -> PrincipalResponse:
    return PrincipalResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        username=principal.username,
        roles=list(principal.roles),
        permissions=sorted(item.value for item in principal.permissions),
        auth_method=principal.auth_method,
    )


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.TENANT_ADMIN)),
) -> UserResponse:
    try:
        user = await get_container().security.create_user(
            principal, body.username, body.password, tuple(body.roles)
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await _audit(request, principal, "user.create", "user", user.user_id, {"roles": body.roles})
    return UserResponse(
        user_id=user.user_id, username=user.username, roles=body.roles, created_at=user.created_at
    )


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.API_KEY_MANAGE)),
) -> ApiKeyResponse:
    try:
        record, raw_key = await get_container().security.create_api_key(
            principal, body.name, tuple(body.roles), body.expires_in_days
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await _audit(
        request,
        principal,
        "api_key.create",
        "api_key",
        record.key_id,
        {"roles": body.roles, "expires_at": str(record.expires_at)},
    )
    return ApiKeyResponse(
        key_id=record.key_id,
        name=record.name,
        key_prefix=record.key_prefix,
        api_key=raw_key,
        roles=list(record.roles),
        expires_at=record.expires_at,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.API_KEY_MANAGE)),
) -> Response:
    if not await get_container().security.revoke_api_key(principal, key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    await _audit(request, principal, "api_key.revoke", "api_key", key_id)
    return Response(status_code=204)


@router.get("/audit-events", response_model=list[AuditEventResponse])
async def audit_events(
    limit: int = 100,
    offset: int = 0,
    principal: SecurityPrincipal = Depends(require_permission(Permission.AUDIT_READ)),
) -> list[AuditEventResponse]:
    events = await get_container().security.repository.list_audit_events(
        principal.tenant_id, min(max(limit, 1), 500), max(offset, 0)
    )
    return [AuditEventResponse(**asdict(event)) for event in events]


async def _audit(
    request: Request,
    principal: SecurityPrincipal,
    action: str,
    resource_type: str,
    resource_id: str = "",
    details: dict | None = None,
) -> None:
    await get_container().security.audit(
        principal,
        action,
        resource_type,
        resource_id,
        ip_address=_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        request_id=request.state.request_id,
        details=details,
    )


def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")
