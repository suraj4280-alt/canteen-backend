from pydantic import BaseModel, Field, field_validator
import re

class RegisterRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=50)
    last_name: str = Field(..., min_length=2, max_length=50)
    middle_name: str | None = Field(None, max_length=50)
    email: str
    uid: str
    hostel: str
    password: str
    phone: str | None = Field(None, max_length=15)
    room_number: str | None = Field(None, max_length=10)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = v.strip()
        if not re.match(r"^[0-9]{10,15}$", cleaned):
            raise ValueError("Phone must be 10-15 digits")
        return cleaned

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[\w\-\.]+@tnu\.in$", v):
            raise ValueError("Email must end with @tnu.in and be a valid format")
        return v

    @field_validator('uid')
    @classmethod
    def validate_uid(cls, v: str) -> str:
        if not re.match(r"^TNU[0-9]{13}$", v):
            raise ValueError("UID must match ^TNU[0-9]{13}$")
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if " " in v:
            raise ValueError("Password must not contain spaces")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[@$!%*?&#^]", v):
            raise ValueError("Password must contain at least one special character")
        return v

class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str
