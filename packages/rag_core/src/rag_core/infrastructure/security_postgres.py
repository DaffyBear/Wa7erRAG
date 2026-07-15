from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rag_core.security import ApiKeyRecord, AuditEvent, Tenant, TenantMembership, UserAccount


class SecurityBase(DeclarativeBase):
    pass


class UserRow(SecurityBase):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TenantRow(SecurityBase):
    __tablename__ = "tenants"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MembershipRow(SecurityBase):
    __tablename__ = "tenant_memberships"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    roles: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiKeyRow(SecurityBase):
    __tablename__ = "api_keys"
    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(32))
    roles: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventRow(SecurityBase):
    __tablename__ = "audit_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_name: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[str] = mapped_column(String(255), default="")
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PostgresSecurityRepository:
    def __init__(self, dsn: str) -> None:
        self.engine: AsyncEngine = create_async_engine(dsn, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(SecurityBase.metadata.create_all)

    async def bootstrap(
        self, user: UserAccount, tenant: Tenant, membership: TenantMembership
    ) -> None:
        async with self.sessions() as session:
            async with session.begin():
                await session.execute(text("SELECT pg_advisory_xact_lock(741936205)"))
                user_count = await session.scalar(select(func.count()).select_from(UserRow))
                tenant_count = await session.scalar(select(func.count()).select_from(TenantRow))
                if user_count or tenant_count:
                    raise ValueError("Security bootstrap has already been completed")
                session.add(UserRow(**vars_from_slots(user)))
                session.add(TenantRow(**vars_from_slots(tenant)))
                membership_values = vars_from_slots(membership)
                membership_values["roles"] = list(membership.roles)
                session.add(MembershipRow(**membership_values))

    async def create_user(self, user: UserAccount) -> None:
        async with self.sessions() as session:
            session.add(UserRow(**vars_from_slots(user)))
            await session.commit()

    async def get_user_by_username(self, username: str) -> UserAccount | None:
        async with self.sessions() as session:
            row = await session.scalar(select(UserRow).where(UserRow.username == username))
        return user_from_row(row)

    async def get_user(self, user_id: str) -> UserAccount | None:
        async with self.sessions() as session:
            row = await session.get(UserRow, user_id)
        return user_from_row(row)

    async def create_tenant(self, tenant: Tenant) -> None:
        async with self.sessions() as session:
            session.add(TenantRow(**vars_from_slots(tenant)))
            await session.commit()

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        async with self.sessions() as session:
            row = await session.get(TenantRow, tenant_id)
        return tenant_from_row(row)

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        async with self.sessions() as session:
            row = await session.scalar(select(TenantRow).where(TenantRow.slug == slug))
        return tenant_from_row(row)

    async def save_membership(self, membership: TenantMembership) -> None:
        async with self.sessions() as session:
            values = vars_from_slots(membership)
            values["roles"] = list(membership.roles)
            await session.merge(MembershipRow(**values))
            await session.commit()

    async def get_membership(self, tenant_id: str, user_id: str) -> TenantMembership | None:
        async with self.sessions() as session:
            row = await session.get(MembershipRow, (tenant_id, user_id))
        return (
            TenantMembership(row.tenant_id, row.user_id, tuple(row.roles), row.created_at)
            if row
            else None
        )

    async def save_api_key(self, api_key: ApiKeyRecord) -> None:
        values = vars_from_slots(api_key)
        values["roles"] = list(api_key.roles)
        async with self.sessions() as session:
            session.add(ApiKeyRow(**values))
            await session.commit()

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        async with self.sessions() as session:
            row = await session.scalar(select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash))
        return api_key_from_row(row)

    async def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        async with self.sessions() as session:
            result = await session.execute(
                update(ApiKeyRow)
                .where(
                    ApiKeyRow.tenant_id == tenant_id,
                    ApiKeyRow.key_id == key_id,
                    ApiKeyRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now().astimezone())
            )
            await session.commit()
        return bool(result.rowcount)

    async def save_audit_event(self, event: AuditEvent) -> None:
        async with self.sessions() as session:
            session.add(AuditEventRow(**vars_from_slots(event)))
            await session.commit()

    async def list_audit_events(self, tenant_id: str, limit: int, offset: int) -> list[AuditEvent]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AuditEventRow)
                    .where(AuditEventRow.tenant_id == tenant_id)
                    .order_by(AuditEventRow.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return [
            AuditEvent(**{name: getattr(row, name) for name in AuditEvent.__dataclass_fields__})
            for row in rows
        ]


def vars_from_slots(value: object) -> dict:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def user_from_row(row: UserRow | None) -> UserAccount | None:
    return (
        UserAccount(
            row.user_id,
            row.username,
            row.password_hash,
            row.is_active,
            row.is_superuser,
            row.created_at,
        )
        if row
        else None
    )


def tenant_from_row(row: TenantRow | None) -> Tenant | None:
    return Tenant(row.tenant_id, row.name, row.slug, row.is_active, row.created_at) if row else None


def api_key_from_row(row: ApiKeyRow | None) -> ApiKeyRecord | None:
    return (
        ApiKeyRecord(
            row.key_id,
            row.tenant_id,
            row.user_id,
            row.name,
            row.key_hash,
            row.key_prefix,
            tuple(row.roles),
            row.expires_at,
            row.revoked_at,
            row.created_at,
        )
        if row
        else None
    )
