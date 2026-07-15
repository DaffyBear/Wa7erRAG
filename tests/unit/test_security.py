import pytest
from rag_core.infrastructure.security_memory import InMemorySecurityRepository
from rag_core.security import JwtCodec, Permission, hash_password, verify_password
from rag_core.security_service import SecurityService


def service() -> SecurityService:
    return SecurityService(
        InMemorySecurityRepository(), JwtCodec("x" * 32, "issuer", "audience", 3600)
    )


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("StrongPassword123!")
    second = hash_password("StrongPassword123!")
    assert first != second
    assert verify_password("StrongPassword123!", first)
    assert not verify_password("wrong-password", first)


@pytest.mark.asyncio
async def test_jwt_roles_api_key_and_revocation() -> None:
    security = service()
    user, tenant = await security.bootstrap("admin", "StrongPassword123!", "Tenant", "tenant")
    token, principal = await security.authenticate_password("admin", "StrongPassword123!", "tenant")
    decoded = await security.authenticate_token(token)
    assert decoded.tenant_id == tenant.tenant_id
    assert decoded.can(Permission.TENANT_ADMIN)

    viewer = await security.create_user(principal, "viewer", "ViewerPassword123!", ("viewer",))
    viewer_token, viewer_principal = await security.authenticate_password(
        "viewer", "ViewerPassword123!", "tenant"
    )
    assert viewer_token
    assert viewer_principal.user_id == viewer.user_id
    assert not viewer_principal.can(Permission.DOCUMENT_WRITE)

    record, raw_key = await security.create_api_key(principal, "automation", ("editor",), 30)
    api_principal = await security.authenticate_api_key(raw_key)
    assert api_principal.auth_method == "api_key"
    assert api_principal.can(Permission.DOCUMENT_WRITE)
    assert await security.revoke_api_key(principal, record.key_id)
    with pytest.raises(ValueError):
        await security.authenticate_api_key(raw_key)


@pytest.mark.asyncio
async def test_audit_events_are_tenant_isolated_and_redacted() -> None:
    security = service()
    _, tenant = await security.bootstrap("admin", "StrongPassword123!", "Tenant", "tenant")
    _, principal = await security.authenticate_password("admin", "StrongPassword123!", "tenant")
    await security.audit(
        principal, "test.action", "resource", details={"password": "secret", "safe": "value"}
    )
    own = await security.repository.list_audit_events(tenant.tenant_id, 10, 0)
    other = await security.repository.list_audit_events("other", 10, 0)
    assert own[0].details == {"password": "[REDACTED]", "safe": "value"}
    assert other == []


@pytest.mark.asyncio
async def test_bootstrap_is_one_time_only() -> None:
    security = service()
    await security.bootstrap("admin", "StrongPassword123!", "Tenant", "tenant")
    with pytest.raises(ValueError, match="already been completed"):
        await security.bootstrap("other", "OtherPassword123!", "Other", "other")


def test_jwt_rejects_modified_algorithm_header() -> None:
    codec = JwtCodec("x" * 32, "issuer", "audience", 3600)
    token = codec.encode("user", "tenant", "name", ("viewer",))
    parts = token.split(".")
    import base64
    import json

    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(ValueError):
        codec.decode(f"{header}.{parts[1]}.{parts[2]}")
