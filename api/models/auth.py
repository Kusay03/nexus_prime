from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    READ_ONLY = "read-only"


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=8)
    role: Role = Role.ANALYST
    tenant_id: str = Field(..., min_length=1)


class BootstrapCreate(BaseModel):
    username: str = Field(..., min_length=3)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=8)
    tenant_id: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    user_id: str
    username: str
    email: str
    role: Role
    tenant_id: str
    created_at: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int      # seconds
    tenant_id: str
    role: str


class BootstrapStatusResponse(BaseModel):
    needs_bootstrap: bool


class CurrentUser(BaseModel):
    """Populated by get_current_user — injected into every protected endpoint."""
    user_id: str
    username: str
    tenant_id: str
    role: Role
    token: str           # raw JWT, kept for blacklist operations
