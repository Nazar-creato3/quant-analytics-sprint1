"""Pydantic schemas for user TOTP 2FA."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class TwoFactorStatusOut(BaseModel):
    enabled: bool
    enabled_at: str | None = None
    backup_codes_remaining: int | None = None
    required_for_admin: bool = False


class TwoFactorEnableInitiateOut(BaseModel):
    secret: str
    provisioning_uri: str
    qr_code_base64: str = ""
    manual_hint: str = ""


class TwoFactorCodeIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)

    @field_validator("code")
    @classmethod
    def digits_only(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned.isdigit() or len(cleaned) not in (6, 7, 8):
            raise ValueError("Код должен быть 6 цифр")
        return cleaned[-6:]


class TwoFactorEnableConfirmIn(TwoFactorCodeIn):
    pass


class TwoFactorEnableConfirmOut(BaseModel):
    success: bool = True
    backup_codes: list[str]
    message: str


class TwoFactorDisableIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)
    password: str = Field(..., min_length=8)

    @field_validator("code")
    @classmethod
    def digits_only(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned.isdigit():
            raise ValueError("Код должен быть 6 цифр")
        return cleaned[-6:]


class TwoFactorLoginVerifyIn(BaseModel):
    pending_token: str = Field(..., min_length=16)
    code: str | None = Field(default=None, min_length=6, max_length=8)
    backup_code: str | None = Field(default=None, min_length=8, max_length=16)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned.isdigit():
            raise ValueError("Код должен быть 6 цифр")
        return cleaned[-6:]

    @field_validator("backup_code")
    @classmethod
    def normalize_backup(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().upper()

    @model_validator(mode="after")
    def require_one_factor(self) -> "TwoFactorLoginVerifyIn":
        if not self.code and not self.backup_code:
            raise ValueError("Укажите TOTP-код или резервный код")
        return self


class TwoFactorReauthIn(TwoFactorCodeIn):
    """Confirm TOTP for a sensitive action (API keys, withdraw, etc.)."""

    pass
