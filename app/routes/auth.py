from fastapi import APIRouter, Depends, HTTPException, status
from asyncpg import Connection
from app.dependencies import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.services.auth_service import hash_password, verify_password, create_access_token, create_refresh_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: Connection = Depends(get_db)):
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
            INSERT INTO students (user_id, first_name, last_name, uid, hostel_id) 
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_id, request.first_name, request.last_name, request.uid, hostel_id
        )

    return {"message": "User registered successfully"}

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Connection = Depends(get_db)):
    # Accept email OR UID
    if "@" in request.identifier:
        # Lookup by email
        user_record = await db.fetchrow(
            """
            SELECT u.id, u.password_hash, u.is_active, r.role_name 
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.email = $1
            """, 
            request.identifier
        )
    else:
        # Lookup by UID
        user_record = await db.fetchrow(
            """
            SELECT u.id, u.password_hash, u.is_active, r.role_name 
            FROM users u
            JOIN students s ON u.id = s.user_id
            JOIN roles r ON u.role_id = r.id
            WHERE s.uid = $1
            """, 
            request.identifier
        )

    if not user_record:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user_record["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled")

    if not verify_password(request.password, user_record["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Generate tokens
    access_token = create_access_token({"sub": str(user_record["id"]), "role": user_record["role_name"]})
    refresh_token = create_refresh_token({"sub": str(user_record["id"])})
    
    # TODO: store session in DB (Phase 3)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )
