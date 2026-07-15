from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from rag_core.security import (
    ApiKeyRecord,
    AuditEvent,
    Tenant,
    TenantMembership,
    UserAccount,
)


class InMemorySecurityRepository:
    def __init__(self) -> None:
        self.users: dict[str, UserAccount] = {}
        self.usernames: dict[str, str] = {}
        self.tenants: dict[str, Tenant] = {}
        self.tenant_slugs: dict[str, str] = {}
        self.memberships: dict[tuple[str, str], TenantMembership] = {}
        self.api_keys: dict[str, ApiKeyRecord] = {}
        self.audit_events: list[AuditEvent] = []
        self.bootstrap_lock = asyncio.Lock()

    async def create_schema(self) -> None:
        return None

    async def bootstrap(
        self, user: UserAccount, tenant: Tenant, membership: TenantMembership
    ) -> None:
        async with self.bootstrap_lock:
            if self.users or self.tenants:
                raise ValueError("Security bootstrap has already been completed")
            await self.create_user(user)
            await self.create_tenant(tenant)
            await self.save_membership(membership)

    async def create_user(self, user: UserAccount) -> None:
        normalized = user.username.casefold()
        if normalized in self.usernames:
            raise ValueError("Username already exists")
        self.users[user.user_id] = user
        self.usernames[normalized] = user.user_id

    async def get_user_by_username(self, username: str) -> UserAccount | None:
        user_id = self.usernames.get(username.casefold())
        return self.users.get(user_id) if user_id else None

    async def get_user(self, user_id: str) -> UserAccount | None:
        return self.users.get(user_id)

    async def create_tenant(self, tenant: Tenant) -> None:
        if tenant.slug.casefold() in self.tenant_slugs:
            raise ValueError("Tenant slug already exists")
        self.tenants[tenant.tenant_id] = tenant
        self.tenant_slugs[tenant.slug.casefold()] = tenant.tenant_id

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.tenants.get(tenant_id)

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        tenant_id = self.tenant_slugs.get(slug.casefold())
        return self.tenants.get(tenant_id) if tenant_id else None

    async def save_membership(self, membership: TenantMembership) -> None:
        self.memberships[(membership.tenant_id, membership.user_id)] = membership

    async def get_membership(self, tenant_id: str, user_id: str) -> TenantMembership | None:
        return self.memberships.get((tenant_id, user_id))

    async def save_api_key(self, api_key: ApiKeyRecord) -> None:
        self.api_keys[api_key.key_hash] = api_key

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        return self.api_keys.get(key_hash)

    async def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        for record in self.api_keys.values():
            if (
                record.tenant_id == tenant_id
                and record.key_id == key_id
                and record.revoked_at is None
            ):
                record.revoked_at = datetime.now(UTC)
                return True
        return False

    async def save_audit_event(self, event: AuditEvent) -> None:
        self.audit_events.append(event)

    async def list_audit_events(self, tenant_id: str, limit: int, offset: int) -> list[AuditEvent]:
        events = [event for event in reversed(self.audit_events) if event.tenant_id == tenant_id]
        return events[offset : offset + limit]
