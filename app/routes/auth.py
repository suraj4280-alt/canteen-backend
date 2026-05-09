from fastapi import APIRouter, Depends, HTTPException, status, Request
from asyncpg import Connection
from jose import jwt, JWTError, ExpiredSignatureError
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from app.dependencies import get_db, get_current_user, get_current_student
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshRequest
from app.services.auth_service import hash_password, verify_password, create_access_token, create_refresh_token
from app.config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address
import hashlib

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Task 7: Profile update schema ───────────────────────────────────────────
class ProfileUpdateReq(BaseModel):
    phone: Optional[str] = Field(None, max_length=15)
    room_number: Optional[str] = Field(None, max_length=10)
    dietary_preference: Optional[str] = Field(None, max_length=20)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import re
        cleaned = v.strip()
        if not re.match(r"^[0-9]{10,15}$", cleaned):
            raise ValueError("Phone must be 10-15 digits")
        return cleaned

    @field_validator('dietary_preference')
    @classmethod
    def validate_dietary(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = ('veg', 'non-veg', 'vegan', 'jain')
        if v not in allowed:
            raise ValueError(f"dietary_preference must be one of: {', '.join(allowed)}")
        return v

# ── Helper: Task 14 — Auth logging ──────────────────────────────────────────
async def _log_auth(db: Connection, user_id: int | None, action: str, success: bool, request: Request, failure_reason: str = None, session_id: int = None):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await db.execute(
        """
        INSERT INTO auth_logs (user_id, action, success, ip_address, user_agent, failure_reason, session_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        user_id, action, success, ip, ua, failure_reason, session_id
    )

# ── Helper: Task 13 — Session management ────────────────────────────────────
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

async def _create_session(db: Connection, user_id: int, access_token: str, refresh_token: str, request: Request) -> int:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    from datetime import datetime, timedelta
    access_expires = datetime.now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_expires = datetime.now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    session_id = await db.fetchval(
        """
        INSERT INTO sessions (user_id, access_token_hash, refresh_token_hash, ip_address, device_info, expires_at, refresh_expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id
        """,
        user_id, _hash_token(access_token), _hash_token(refresh_token),
        ip, ua, access_expires, refresh_expires
    )
    return session_id


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(request: RegisterRequest, req: Request, db: Connection = Depends(get_db)):
    # 1. Check if email exists
    existing_user = await db.fetchrow("SELECT id FROM users WHERE email = $1", request.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Check if UID exists
    existing_student = await db.fetchrow("SELECT id FROM students WHERE uid = $1", request.uid)
    if existing_student:
        raise HTTPException(status_code=400, detail="UID already registered")

    # 3. Get role_id for 'student'
    role = await db.fetchrow("SELECT id FROM roles WHERE role_name = 'student'")
    if not role:
        raise HTTPException(status_code=500, detail="Student role not found in database")
    role_id = role["id"]

    # 4. Get hostel_id
    hostel = await db.fetchrow("SELECT id FROM hostels WHERE name = $1", request.hostel)
    if not hostel:
        raise HTTPException(status_code=400, detail="Invalid hostel name")
    hostel_id = hostel["id"]

    # 5. Insert into users and students
    hashed_password = hash_password(request.password)
    
    async with db.transaction():
        user_id = await db.fetchval(
            "INSERT INTO users (role_id, email, password_hash) VALUES ($1, $2, $3) RETURNING id",
            role_id, request.email, hashed_password
        )
        
        await db.execute(
            """
            INSERT INTO students (user_id, first_name, middle_name, last_name, uid, hostel_id, phone, room_number) 
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            user_id, request.first_name, request.middle_name, request.last_name, request.uid, hostel_id, request.phone, request.room_number
        )

    return {"message": "User registered successfully"}

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(login_data: LoginRequest, request: Request, db: Connection = Depends(get_db)):
    # Accept email OR UID
    if "@" in login_data.identifier:
        user_record = await db.fetchrow(
            """
            SELECT u.id, u.password_hash, u.is_active, u.login_attempts, u.locked_until, r.role_name 
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.email = $1
            """, 
            login_data.identifier
        )
    else:
        user_record = await db.fetchrow(
            """
            SELECT u.id, u.password_hash, u.is_active, u.login_attempts, u.locked_until, r.role_name 
            FROM users u
            JOIN students s ON u.id = s.user_id
            JOIN roles r ON u.role_id = r.id
            WHERE s.uid = $1
            """, 
            login_data.identifier
        )

    if not user_record:
        await _log_auth(db, None, "login", False, request, failure_reason="User not found")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user_record["is_active"]:
        await _log_auth(db, user_record["id"], "login", False, request, failure_reason="Account disabled")
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Check account lockout
    from datetime import datetime, timedelta
    if user_record["locked_until"] and user_record["locked_until"] > datetime.now():
        remaining = int((user_record["locked_until"] - datetime.now()).total_seconds() // 60) + 1
        await _log_auth(db, user_record["id"], "login", False, request, failure_reason="Account locked")
        raise HTTPException(status_code=403, detail=f"Account is locked. Try again in {remaining} minute(s).")

    if not verify_password(login_data.password, user_record["password_hash"]):
        # Increment login attempts
        new_attempts = (user_record["login_attempts"] or 0) + 1
        if new_attempts >= 5:
            lock_until = datetime.now() + timedelta(minutes=15)
            await db.execute(
                "UPDATE users SET login_attempts = $1, locked_until = $2 WHERE id = $3",
                new_attempts, lock_until, user_record["id"]
            )
            await _log_auth(db, user_record["id"], "account_locked", False, request, failure_reason="Too many failed attempts")
            raise HTTPException(status_code=403, detail="Account locked for 15 minutes due to too many failed attempts.")
        else:
            await db.execute(
                "UPDATE users SET login_attempts = $1 WHERE id = $2",
                new_attempts, user_record["id"]
            )
        await _log_auth(db, user_record["id"], "failed_login", False, request, failure_reason="Wrong password")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Generate tokens
    access_token = create_access_token({"sub": str(user_record["id"]), "role": user_record["role_name"]})
    refresh_token = create_refresh_token({"sub": str(user_record["id"])})
    
    # Task 13: Store session in DB
    session_id = await _create_session(db, user_record["id"], access_token, refresh_token, request)
    
    # Task 14: Log successful login
    await _log_auth(db, user_record["id"], "login", True, request, session_id=session_id)
    
    # Reset login attempts and update last login on success
    await db.execute(
        "UPDATE users SET login_attempts = 0, locked_until = NULL, last_login_at = NOW(), last_login_ip = $1 WHERE id = $2",
        request.client.host if request.client else None, user_record["id"]
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest, req: Request, db: Connection = Depends(get_db)):
    try:
        payload = jwt.decode(request.refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = int(user_id_str)
        user = await db.fetchrow(
            """
            SELECT u.id, u.is_active, r.role_name 
            FROM users u 
            JOIN roles r ON u.role_id = r.id 
            WHERE u.id = $1
            """,
            user_id
        )
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account is disabled")
        
        # Task 13: Validate session exists and is not revoked
        old_hash = _hash_token(request.refresh_token)
        session = await db.fetchrow(
            "SELECT id FROM sessions WHERE refresh_token_hash = $1 AND revoked = FALSE",
            old_hash
        )
        if not session:
            await _log_auth(db, user_id, "token_refresh", False, req, failure_reason="Session not found or revoked")
            raise HTTPException(status_code=401, detail="Session invalid or revoked")
        
        new_access = create_access_token({"sub": str(user["id"]), "role": user["role_name"]})
        new_refresh = create_refresh_token({"sub": str(user["id"])})
        
        # Task 13: Revoke old session, create new one
        await db.execute("UPDATE sessions SET revoked = TRUE, revoked_at = NOW(), revoked_reason = 'rotated' WHERE id = $1", session["id"])
        new_session_id = await _create_session(db, user_id, new_access, new_refresh, req)
        
        # Task 14: Log refresh
        await _log_auth(db, user_id, "token_refresh", True, req, session_id=new_session_id)
        
        return TokenResponse(access_token=new_access, refresh_token=new_refresh)
        
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@router.post("/logout")
async def logout(req: Request, current_user: dict = Depends(get_current_user), db: Connection = Depends(get_db)):
    """Task 13: Revoke current session on logout."""
    # We don't have the exact token hash here, so we revoke all active sessions for this user
    # A more precise approach would extract the token from the Authorization header
    auth_header = req.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_hash = _hash_token(token)
        session = await db.fetchrow(
            "SELECT id FROM sessions WHERE access_token_hash = $1 AND revoked = FALSE",
            token_hash
        )
        if session:
            await db.execute(
                "UPDATE sessions SET revoked = TRUE, revoked_at = NOW(), logout_at = NOW(), revoked_reason = 'logout' WHERE id = $1",
                session["id"]
            )
    
    await _log_auth(db, current_user["id"], "logout", True, req)
    return {"message": "Logged out successfully"}

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), db: Connection = Depends(get_db)):
    user_id = current_user["id"]
    role = current_user["role_name"]

    # Base user info
    result = {
        "id": user_id,
        "role": role,
    }

    if role == "student":
        student = await db.fetchrow(
            """
            SELECT s.first_name, s.middle_name, s.last_name, s.uid, s.phone,
                   s.room_number, s.dietary_preference, h.name as hostel_name,
                   u.email
            FROM students s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN hostels h ON s.hostel_id = h.id
            WHERE s.user_id = $1 AND s.is_active = TRUE
            """,
            user_id
        )
        if student:
            result.update({
                "firstName": student["first_name"],
                "middleName": student["middle_name"] or "",
                "lastName": student["last_name"],
                "uid": student["uid"],
                "phone": student["phone"] or "",
                "room": student["room_number"] or "",
                "hostel": student["hostel_name"] or "",
                "email": student["email"],
                "dietary_preference": student["dietary_preference"] or "veg",
            })
    elif role in ("canteen_staff", "admin", "warden"):
        staff = await db.fetchrow(
            """
            SELECT s.first_name, s.last_name, s.phone, s.designation,
                   h.name as hostel_name, u.email
            FROM staff s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN hostels h ON s.hostel_id = h.id
            WHERE s.user_id = $1 AND s.is_active = TRUE
            """,
            user_id
        )
        if staff:
            result.update({
                "firstName": staff["first_name"],
                "lastName": staff["last_name"],
                "phone": staff["phone"] or "",
                "designation": staff["designation"] or "",
                "hostel": staff["hostel_name"] or "",
                "email": staff["email"],
            })

    return result

# ── Task 7: Profile update ──────────────────────────────────────────────────
@router.put("/profile")
async def update_profile(request: ProfileUpdateReq, current_user: dict = Depends(get_current_user), db: Connection = Depends(get_db)):
    """Update student phone and room_number only."""
    if current_user["role_name"] != "student":
        raise HTTPException(status_code=403, detail="Only students can update their profile here")
    
    student = await db.fetchrow("SELECT id FROM students WHERE user_id = $1 AND is_active = TRUE", current_user["id"])
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found")
    
    updates = []
    params = []
    param_idx = 1
    
    if request.phone is not None:
        updates.append(f"phone = ${param_idx}")
        params.append(request.phone)
        param_idx += 1
    
    if request.room_number is not None:
        updates.append(f"room_number = ${param_idx}")
        params.append(request.room_number)
        param_idx += 1
    
    if request.dietary_preference is not None:
        updates.append(f"dietary_preference = ${param_idx}")
        params.append(request.dietary_preference)
        param_idx += 1
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    params.append(student["id"])
    query = f"UPDATE students SET {', '.join(updates)} WHERE id = ${param_idx}"
    await db.execute(query, *params)
    
    return {"message": "Profile updated successfully"}
