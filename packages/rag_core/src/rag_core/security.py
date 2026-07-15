from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol


class Permission(StrEnum):
    CHAT_USE = "chat:use"
    SESSION_READ = "session:read"
    SESSION_DELETE = "session:delete"
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    GOVERNANCE_READ = "governance:read"
    GOVERNANCE_WRITE = "governance:write"
    AUDIT_READ = "audit:read"
    TENANT_ADMIN = "tenant:admin"
    API_KEY_MANAGE = "api_key:manage"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "viewer": frozenset({Permission.CHAT_USE, Permission.SESSION_READ, Permission.DOCUMENT_READ}),
    "editor": frozenset(
        {
            Permission.CHAT_USE,
            Permission.SESSION_READ,
            Permission.SESSION_DELETE,
            Permission.DOCUMENT_READ,
            Permission.DOCUMENT_WRITE,
        }
    ),
    "auditor": frozenset({Permission.AUDIT_READ, Permission.GOVERNANCE_READ}),
    "admin": frozenset(Permission),
}


@dataclass(frozen=True, slots=True)
class SecurityPrincipal:
    user_id: str
    tenant_id: str
    username: str
    roles: tuple[str, ...]
    permissions: frozenset[Permission]
    auth_method: str
    api_key_id: str | None = None

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


@dataclass(slots=True)
class UserAccount:
    user_id: str
    username: str
    password_hash: str
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class Tenant:
    tenant_id: str
    name: str
    slug: str
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class TenantMembership:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ApiKeyRecord:
    key_id: str
    tenant_id: str
    user_id: str
    name: str
    key_hash: str
    key_prefix: str
    roles: tuple[str, ...]
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class AuditEvent:
    event_id: str
    tenant_id: str
    actor_id: str
    actor_name: str
    action: str
    resource_type: str
    resource_id: str = ""
    outcome: str = "success"
    ip_address: str = ""
    user_agent: str = ""
    request_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SecurityRepository(Protocol):
    async def create_schema(self) -> None: ...
    async def bootstrap(
        self, user: UserAccount, tenant: Tenant, membership: TenantMembership
    ) -> None: ...
    async def create_user(self, user: UserAccount) -> None: ...
    async def get_user_by_username(self, username: str) -> UserAccount | None: ...
    async def get_user(self, user_id: str) -> UserAccount | None: ...
    async def create_tenant(self, tenant: Tenant) -> None: ...
    async def get_tenant(self, tenant_id: str) -> Tenant | None: ...
    async def get_tenant_by_slug(self, slug: str) -> Tenant | None: ...
    async def save_membership(self, membership: TenantMembership) -> None: ...
    async def get_membership(self, tenant_id: str, user_id: str) -> TenantMembership | None: ...
    async def save_api_key(self, api_key: ApiKeyRecord) -> None: ...
    async def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None: ...
    async def revoke_api_key(self, tenant_id: str, key_id: str) -> bool: ...
    async def save_audit_event(self, event: AuditEvent) -> None: ...
    async def list_audit_events(
        self, tenant_id: str, limit: int, offset: int
    ) -> list[AuditEvent]: ...


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=actual_salt, n=2**14, r=8, p=1, dklen=32)
    return (
        "scrypt$16384$8$1$"
        + base64.urlsafe_b64encode(actual_salt).decode()
        + "$"
        + base64.urlsafe_b64encode(digest).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def issue_api_key() -> tuple[str, str, str]:
    key_id = uuid.uuid4().hex
    secret = secrets.token_urlsafe(32)
    raw_key = f"rag_{key_id[:12]}_{secret}"
    return key_id, raw_key, raw_key[:20]


def permissions_for_roles(roles: tuple[str, ...] | list[str]) -> frozenset[Permission]:
    permissions: set[Permission] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, ()))
    return frozenset(permissions)


class JwtCodec:
    def __init__(self, secret: str, issuer: str, audience: str, ttl_seconds: int) -> None:
        if len(secret) < 32:
            raise ValueError("JWT secret must contain at least 32 characters")
        self.secret = secret.encode()
        self.issuer = issuer
        self.audience = audience
        self.ttl_seconds = ttl_seconds

    def encode(self, user_id: str, tenant_id: str, username: str, roles: tuple[str, ...]) -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "tid": tenant_id,
            "username": username,
            "roles": list(roles),
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + self.ttl_seconds,
            "jti": uuid.uuid4().hex,
        }
        header = {"alg": "HS256", "typ": "JWT"}
        encoded_header = _b64json(header)
        encoded_payload = _b64json(payload)
        signature = _b64(
            hmac.new(
                self.secret, f"{encoded_header}.{encoded_payload}".encode(), hashlib.sha256
            ).digest()
        )
        return f"{encoded_header}.{encoded_payload}.{signature}"

    def decode(self, token: str) -> dict[str, Any]:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
            header = json.loads(_unb64(encoded_header))
            if header != {"alg": "HS256", "typ": "JWT"}:
                raise ValueError("Unsupported token algorithm")
            expected = _b64(
                hmac.new(
                    self.secret, f"{encoded_header}.{encoded_payload}".encode(), hashlib.sha256
                ).digest()
            )
            if not hmac.compare_digest(expected, encoded_signature):
                raise ValueError("Invalid token signature")
            payload = json.loads(_unb64(encoded_payload))
        except (ValueError, json.JSONDecodeError) as error:
            raise ValueError("Invalid access token") from error
        now = int(time.time())
        if payload.get("iss") != self.issuer or payload.get("aud") != self.audience:
            raise ValueError("Invalid token issuer or audience")
        if int(payload.get("exp", 0)) <= now:
            raise ValueError("Access token expired")
        if not payload.get("sub") or not payload.get("tid"):
            raise ValueError("Token is missing subject or tenant")
        return payload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64json(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())
