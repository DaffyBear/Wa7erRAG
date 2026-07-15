from datetime import datetime

from pydantic import BaseModel, Field


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    tenant_name: str = Field(min_length=2, max_length=255)
    tenant_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_slug: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tenant_id: str
    user_id: str
    roles: list[str]


class PrincipalResponse(BaseModel):
    user_id: str
    tenant_id: str
    username: str
    roles: list[str]
    permissions: list[str]
    auth_method: str


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    roles: list[str] = Field(min_length=1)


class UserResponse(BaseModel):
    user_id: str
    username: str
    roles: list[str]
    created_at: datetime


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    roles: list[str] = Field(min_length=1)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    api_key: str
    roles: list[str]
    expires_at: datetime | None


class AuditEventResponse(BaseModel):
    event_id: str
    tenant_id: str
    actor_id: str
    actor_name: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    ip_address: str
    user_agent: str
    request_id: str
    details: dict
    created_at: datetime
