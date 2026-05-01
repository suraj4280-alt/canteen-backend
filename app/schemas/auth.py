from pydantic import BaseModel, Field, field_validator
import re

class RegisterRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=50)
    last_name: str = Field(..., min_length=2, max_length=50)
    email: str
    uid: str
    hostel: str
    password: str

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
