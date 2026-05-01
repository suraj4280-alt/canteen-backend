from fastapi import Request, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError, ExpiredSignatureError
from asyncpg import Connection
from app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

async def get_db():
    from app.database import pool
    async with pool.acquire() as connection:
        yield connection

async def get_current_user(token: str = Depends(oauth2_scheme), db: Connection = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
        token_type = payload.get("type")
        if token_type != "access":
            raise credentials_exception
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired", headers={"WWW-Authenticate": "Bearer"})
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})
        
    user = await db.fetchrow(
        """
        SELECT u.id, u.is_active, r.role_name 
        FROM users u 
        JOIN roles r ON u.role_id = r.id 
        WHERE u.id = $1
        """, 
        user_id
    )
    if user is None:
        raise credentials_exception
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Inactive user")
        
    return dict(user)

def require_role(allowed_roles: list[str]):
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role_name"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return current_user
    return role_checker

async def require_staff(current_user: dict = Depends(get_current_user), db: Connection = Depends(get_db)):
    staff = await db.fetchrow("SELECT id FROM staff WHERE user_id = $1 AND is_active = TRUE", current_user["id"])
    if not staff:
        raise HTTPException(status_code=403, detail="User is not active staff")
    
    current_user["staff_id"] = staff["id"]
    return current_user

async def get_current_student(current_user: dict = Depends(require_role(["student"])), db: Connection = Depends(get_db)):
    student = await db.fetchrow("SELECT id, hostel_id FROM students WHERE user_id = $1 AND is_active = TRUE", current_user["id"])
    if not student:
        raise HTTPException(status_code=403, detail="Active student profile not found")
        
    current_user["student_id"] = student["id"]
    current_user["hostel_id"] = student["hostel_id"]
    return current_user
