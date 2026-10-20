from uuid import UUID
from typing import Literal

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.models.seller_membership import SellerRole


class SellerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    company_name: str = Field(min_length=1, max_length=255)


class SellerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    company_name: str
    is_active: bool
    account_status: str
    email_verified_at: datetime | None


class SellerPermissionsResponse(BaseModel):
    role: SellerRole
    permissions: list[str]


class SellerRegistrationResponse(BaseModel):
    status: str
    message: str


class SellerSuspensionResponse(BaseModel):
    status: str = "SUSPENDED"


class SellerInviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Literal[
        "MANAGER",
        "CATALOG_EDITOR",
        "WAREHOUSE_OPERATOR",
        "SUPPORT",
        "FINANCE",
        "VIEWER",
    ]


class SellerInviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=128)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class SellerInviteResponse(BaseModel):
    id: UUID
    role: SellerRole
    expires_at: datetime
    status: str = "PENDING"


class SellerInviteAcceptResponse(BaseModel):
    status: str
    email: EmailStr
    seller_id: UUID
    role: SellerRole


class SellerMemberResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: SellerRole
    active: bool
    created_at: datetime
    revision: int = Field(ge=1)


class SellerMemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SellerRole
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("role")
    @classmethod
    def prevent_owner_assignment(cls, value: SellerRole) -> SellerRole:
        if value == SellerRole.OWNER:
            raise ValueError("OWNER cannot be assigned through member role changes")
        return value

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return value


class SellerMembershipRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return value


class EmailVerificationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class EmailVerificationResendRequest(BaseModel):
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(ge=1, le=900)


class SellerSessionResponse(BaseModel):
    id: UUID
    seller_id: UUID
    device_label: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class SellerOrganizationResponse(BaseModel):
    id: UUID
    company_name: str
    role: SellerRole
    current: bool


class SellerTenantSwitchRequest(BaseModel):
    seller_id: UUID
