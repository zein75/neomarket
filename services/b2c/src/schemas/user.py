from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    first_name: str | None
    last_name: str | None
    phone: str | None
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(default=900, ge=1)
    refresh_token: str | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class AddressInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=100)
    address_line: str = Field(min_length=1, max_length=500)


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    address_line: str

    @model_validator(mode="before")
    @classmethod
    def support_legacy_rows(cls, value):
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {
                "id": value.id,
                "label": getattr(value, "label", None),
                "address_line": getattr(value, "address_line", None),
                "city": getattr(value, "city", None),
                "street": getattr(value, "street", None),
            }
        data["label"] = data.get("label") or data.get("city") or "Address"
        data["address_line"] = data.get("address_line") or data.get("street") or ""
        return data


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_token: str = Field(min_length=1)
    new_password: str = Field(min_length=12)
