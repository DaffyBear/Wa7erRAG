from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from rag_core.security import (
    ApiKeyRecord,
    AuditEvent,
    JwtCodec,
    Permission,
    SecurityPrincipal,
    SecurityRepository,
    Tenant,
    TenantMembership,
    UserAccount,
    hash_api_key,
    hash_password,
    issue_api_key,
    permissions_for_roles,
    verify_password,
)


class SecurityService:
    def __init__(self, repository: SecurityRepository, jwt_codec: JwtCodec) -> None:
        self.repository = repository
        self.jwt_codec = jwt_codec

    async def bootstrap(
        self, username: str, password: str, tenant_name: str, tenant_slug: str
    ) -> tuple[UserAccount, Tenant]:
        user = UserAccount(
            uuid.uuid4().hex,
            username.strip().casefold(),
            hash_password(password),
            is_superuser=True,
        )
        tenant = Tenant(uuid.uuid4().hex, tenant_name.strip(), tenant_slug.strip().casefold())
        membership = TenantMembership(tenant.tenant_id, user.user_id, ("admin",))
        await self.repository.bootstrap(user, tenant, membership)
        return user, tenant

    async def authenticate_password(
        self, username: str, password: str, tenant_slug: str
    ) -> tuple[str, SecurityPrincipal]:
        user = await self.repository.get_user_by_username(username.strip().casefold())
        tenant = await self.repository.get_tenant_by_slug(tenant_slug)
        if user is None or tenant is None or not user.is_active or not tenant.is_active:
            raise ValueError("Invalid credentials")
        if not verify_password(password, user.password_hash):
            raise ValueError("Invalid credentials")
        membership = await self.repository.get_membership(tenant.tenant_id, user.user_id)
        if membership is None:
            raise ValueError("Invalid credentials")
        principal = self._principal(user, tenant, membership.roles, "bearer")
        return self.jwt_codec.encode(
            user.user_id, tenant.tenant_id, user.username, membership.roles
        ), principal

    async def authenticate_token(self, token: str) -> SecurityPrincipal:
        payload = self.jwt_codec.decode(token)
        user = await self.repository.get_user(str(payload["sub"]))
        tenant = await self.repository.get_tenant(str(payload["tid"]))
        if user is None or tenant is None or not user.is_active or not tenant.is_active:
            raise ValueError("Access token subject is inactive")
        membership = await self.repository.get_membership(tenant.tenant_id, user.user_id)
        if membership is None:
            raise ValueError("Tenant membership not found")
        token_roles = tuple(str(role) for role in payload.get("roles", []))
        if set(token_roles) != set(membership.roles):
            raise ValueError("Access token roles are stale")
        return self._principal(user, tenant, membership.roles, "bearer")

    async def authenticate_api_key(self, raw_key: str) -> SecurityPrincipal:
        record = await self.repository.get_api_key_by_hash(hash_api_key(raw_key))
        now = datetime.now(UTC)
        if (
            record is None
            or record.revoked_at is not None
            or (record.expires_at and record.expires_at <= now)
        ):
            raise ValueError("Invalid API key")
        user = await self.repository.get_user(record.user_id)
        tenant = await self.repository.get_tenant(record.tenant_id)
        membership = await self.repository.get_membership(record.tenant_id, record.user_id)
        if (
            user is None
            or tenant is None
            or membership is None
            or not user.is_active
            or not tenant.is_active
        ):
            raise ValueError("API key subject is inactive")
        membership_permissions = permissions_for_roles(membership.roles)
        key_permissions = permissions_for_roles(record.roles)
        if not key_permissions.issubset(membership_permissions):
            raise ValueError("API key permissions exceed current membership")
        return self._principal(user, tenant, record.roles, "api_key", record.key_id)

    async def create_user(
        self, principal: SecurityPrincipal, username: str, password: str, roles: tuple[str, ...]
    ) -> UserAccount:
        self.require(principal, Permission.TENANT_ADMIN)
        self._validate_roles(roles)
        user = UserAccount(uuid.uuid4().hex, username.strip().casefold(), hash_password(password))
        await self.repository.create_user(user)
        await self.repository.save_membership(
            TenantMembership(principal.tenant_id, user.user_id, roles)
        )
        return user

    async def create_api_key(
        self,
        principal: SecurityPrincipal,
        name: str,
        roles: tuple[str, ...],
        expires_in_days: int | None,
    ) -> tuple[ApiKeyRecord, str]:
        self.require(principal, Permission.API_KEY_MANAGE)
        self._validate_roles(roles)
        if not permissions_for_roles(roles).issubset(principal.permissions):
            raise PermissionError("API key cannot exceed actor permissions")
        key_id, raw_key, prefix = issue_api_key()
        expires_at = (
            datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None
        )
        record = ApiKeyRecord(
            key_id,
            principal.tenant_id,
            principal.user_id,
            name,
            hash_api_key(raw_key),
            prefix,
            roles,
            expires_at,
        )
        await self.repository.save_api_key(record)
        return record, raw_key

    async def revoke_api_key(self, principal: SecurityPrincipal, key_id: str) -> bool:
        self.require(principal, Permission.API_KEY_MANAGE)
        return await self.repository.revoke_api_key(principal.tenant_id, key_id)

    async def audit(
        self,
        principal: SecurityPrincipal | None,
        action: str,
        resource_type: str,
        resource_id: str = "",
        outcome: str = "success",
        ip_address: str = "",
        user_agent: str = "",
        request_id: str = "",
        details: dict | None = None,
        tenant_id: str = "",
    ) -> AuditEvent:
        event = AuditEvent(
            uuid.uuid4().hex,
            principal.tenant_id if principal else tenant_id,
            principal.user_id if principal else "anonymous",
            principal.username if principal else "anonymous",
            action,
            resource_type,
            resource_id,
            outcome,
            ip_address,
            user_agent[:512],
            request_id,
            _sanitize(details or {}),
        )
        await self.repository.save_audit_event(event)
        return event

    @staticmethod
    def require(principal: SecurityPrincipal, permission: Permission) -> None:
        if not principal.can(permission):
            raise PermissionError(f"Missing permission: {permission.value}")

    @staticmethod
    def _validate_roles(roles: tuple[str, ...]) -> None:
        unknown = sorted(set(roles) - {"viewer", "editor", "auditor", "admin"})
        if not roles or unknown:
            raise ValueError(f"Invalid roles: {unknown or 'empty'}")

    @staticmethod
    def _principal(
        user: UserAccount,
        tenant: Tenant,
        roles: tuple[str, ...],
        method: str,
        api_key_id: str | None = None,
    ) -> SecurityPrincipal:
        return SecurityPrincipal(
            user.user_id,
            tenant.tenant_id,
            user.username,
            roles,
            permissions_for_roles(roles),
            method,
            api_key_id,
        )


def _sanitize(value: object) -> object:
    sensitive = {"password", "token", "authorization", "api_key", "secret"}
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).casefold() in sensitive else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return value[:2000]
    return value
