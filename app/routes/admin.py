"""
Admin API routes for the CanteenOS Admin Dashboard.
All routes are protected by require_admin dependency.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from asyncpg import Connection
from pydantic import BaseModel, Field, field_validator
import re
import aiofiles
import uuid
import os
from typing import Optional
from datetime import date, datetime
from app.dependencies import get_db, get_current_user
from app.services.auth_service import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Dependency: Require admin role ───────────────────────────────────────────
async def require_admin(user: dict = Depends(get_current_user)):
    if user["role_name"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Schemas ──────────────────────────────────────────────────────────────────

class MenuItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: Optional[str] = Field(None, pattern=r"^(veg|non-veg|beverage|dessert|snack)$")
    description: Optional[str] = None
    allergens: Optional[str] = None
    spice_level: Optional[int] = Field(None, ge=0, le=3)
    unit: Optional[str] = "plate"

class MenuItemUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, pattern=r"^(veg|non-veg|beverage|dessert|snack)$")
    description: Optional[str] = None
    allergens: Optional[str] = None
    spice_level: Optional[int] = Field(None, ge=0, le=3)
    unit: Optional[str] = None

class MealMenuSave(BaseModel):
    hostel_id: int
    meal_slot_id: int
    date: date
    item_ids: list[int]

class StaffCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    phone: Optional[str] = Field(None, max_length=15)
    email: str
    password: str = Field(..., min_length=8)
    designation: Optional[str] = None
    hostel_id: Optional[int] = None

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
            raise ValueError("Password must contain at least one special character (@$!%*?&#^)")
        return v

class StaffUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    phone: Optional[str] = Field(None, max_length=15)
    designation: Optional[str] = None
    hostel_id: Optional[int] = None


# ══════════════════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_admin_stats(
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Dashboard statistics for index.html."""
    today = date.today()
    now_time = datetime.now().time()

    # Total active students
    total_students = await db.fetchval(
        "SELECT COUNT(*) FROM students WHERE is_active = TRUE"
    )

    # Total active staff
    total_staff = await db.fetchval(
        "SELECT COUNT(*) FROM staff WHERE is_active = TRUE"
    )

    # Bookings today (booked + used)
    bookings_today = await db.fetchval("""
        SELECT COUNT(*) FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.date = $1 AND bs.status_name IN ('booked', 'used')
    """, today)

    # Meals served today (status = used)
    meals_served_today = await db.fetchval("""
        SELECT COUNT(*) FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.date = $1 AND bs.status_name = 'used'
    """, today)

    # Active hostels
    active_hostels = await db.fetchval(
        "SELECT COUNT(*) FROM hostels WHERE is_active = TRUE"
    )

    # Skips today
    skips_today = await db.fetchval("""
        SELECT COUNT(*) FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.date = $1 AND bs.status_name IN ('skipped', 'absent', 'missed')
    """, today)

    # Per-slot breakdown
    slots = await db.fetch(
        "SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY display_order"
    )
    per_slot = []
    for slot in slots:
        total_booked = await db.fetchval("""
            SELECT COUNT(*) FROM bookings b
            JOIN booking_status bs ON b.status_id = bs.id
            WHERE b.meal_slot_id = $1 AND b.date = $2
              AND bs.status_name IN ('booked', 'used')
        """, slot["id"], today)

        total_served = await db.fetchval("""
            SELECT COUNT(*) FROM bookings b
            JOIN booking_status bs ON b.status_id = bs.id
            WHERE b.meal_slot_id = $1 AND b.date = $2
              AND bs.status_name = 'used'
        """, slot["id"], today)

        total_skipped = await db.fetchval("""
            SELECT COUNT(*) FROM bookings b
            JOIN booking_status bs ON b.status_id = bs.id
            WHERE b.meal_slot_id = $1 AND b.date = $2
              AND bs.status_name IN ('skipped', 'absent', 'missed')
        """, slot["id"], today)

        # Determine slot status
        if now_time > slot["end_time"]:
            slot_status = "closed"
        elif now_time >= slot["start_time"]:
            slot_status = "active"
        else:
            slot_status = "upcoming"

        per_slot.append({
            "slot_id": slot["id"],
            "slot_name": slot["name"],
            "start_time": slot["start_time"].strftime("%I:%M %p"),
            "end_time": slot["end_time"].strftime("%I:%M %p"),
            "total_booked": total_booked or 0,
            "total_served": total_served or 0,
            "total_skipped": total_skipped or 0,
            "status": slot_status,
            "color_code": slot.get("color_code", "#4CAF50"),
        })

    return {
        "total_students": total_students or 0,
        "total_staff": total_staff or 0,
        "bookings_today": bookings_today or 0,
        "meals_served_today": meals_served_today or 0,
        "active_hostels": active_hostels or 0,
        "skips_today": skips_today or 0,
        "per_slot": per_slot,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MENU ITEMS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/menu-items")
async def get_menu_items(
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Returns all menu items (active and inactive)."""
    items = await db.fetch(
        "SELECT * FROM menu_items ORDER BY name"
    )
    return [dict(item) for item in items]


@router.post("/menu-items", status_code=status.HTTP_201_CREATED)
async def create_menu_item(
    body: MenuItemCreate,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Create a new menu item."""
    existing = await db.fetchrow(
        "SELECT id FROM menu_items WHERE name = $1", body.name
    )
    if existing:
        raise HTTPException(status_code=400, detail="Menu item with this name already exists")

    item_id = await db.fetchval("""
        INSERT INTO menu_items (name, type, description, allergens, spice_level, unit, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id
    """, body.name, body.type, body.description, body.allergens,
        body.spice_level, body.unit, admin["id"])

    return {"id": item_id, "message": "Menu item created"}


@router.post("/menu-items/{item_id}/image")
async def upload_menu_item_image(
    item_id: int,
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Upload an image for a menu item."""
    item = await db.fetchrow("SELECT id FROM menu_items WHERE id = $1", item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and WebP images are allowed.")

    # Validate file size (2MB max)
    file_bytes = await file.read()
    if len(file_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 2MB limit.")

    # Save file
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join("uploads", filename)
    
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(file_bytes)

    # Store URL in DB
    image_url = f"/static/{filename}"
    await db.execute("UPDATE menu_items SET image_url = $1 WHERE id = $2", image_url, item_id)

    return {"image_url": image_url, "message": "Image uploaded successfully"}


@router.put("/menu-items/{item_id}")
async def update_menu_item(
    item_id: int,
    body: MenuItemUpdate,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Update an existing menu item."""
    item = await db.fetchrow("SELECT id FROM menu_items WHERE id = $1", item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    updates = []
    params = []
    idx = 1
    for field_name, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field_name} = ${idx}")
        params.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(item_id)
    query = f"UPDATE menu_items SET {', '.join(updates)} WHERE id = ${idx}"
    await db.execute(query, *params)
    return {"message": "Menu item updated"}


@router.delete("/menu-items/{item_id}")
async def delete_menu_item(
    item_id: int,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Soft delete a menu item (set is_active = false)."""
    item = await db.fetchrow("SELECT id FROM menu_items WHERE id = $1", item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    await db.execute("UPDATE menu_items SET is_active = FALSE WHERE id = $1", item_id)
    return {"message": "Menu item deactivated"}


# ══════════════════════════════════════════════════════════════════════════════
# MEAL MENUS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/meal-menus")
async def get_meal_menus(
    hostel_id: int,
    date: date,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Returns meal menus for a specific hostel and date, including items per slot."""
    menus = await db.fetch("""
        SELECT mm.*, ms.name as slot_name, ms.display_order
        FROM meal_menus mm
        JOIN meal_slots ms ON mm.meal_slot_id = ms.id
        WHERE mm.hostel_id = $1 AND mm.date = $2
        ORDER BY ms.display_order
    """, hostel_id, date)

    result = []
    for menu in menus:
        items = await db.fetch("""
            SELECT mi.*, mmi.exclusive_group, mmi.sort_order
            FROM menu_items mi
            JOIN meal_menu_items mmi ON mi.id = mmi.menu_item_id
            WHERE mmi.meal_menu_id = $1 AND mi.is_active = TRUE
            ORDER BY mmi.sort_order
        """, menu["id"])

        result.append({
            "id": menu["id"],
            "hostel_id": menu["hostel_id"],
            "meal_slot_id": menu["meal_slot_id"],
            "slot_name": menu["slot_name"],
            "date": str(menu["date"]),
            "is_published": menu["is_published"],
            "items": [dict(item) for item in items],
        })

    return result


@router.post("/meal-menus")
async def save_meal_menu(
    body: MealMenuSave,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Create or update a meal menu for a hostel + date + slot."""
    # Check if menu already exists
    existing = await db.fetchrow("""
        SELECT id FROM meal_menus
        WHERE hostel_id = $1 AND meal_slot_id = $2 AND date = $3
    """, body.hostel_id, body.meal_slot_id, body.date)

    async with db.transaction():
        if existing:
            menu_id = existing["id"]
            # Delete old items
            await db.execute(
                "DELETE FROM meal_menu_items WHERE meal_menu_id = $1", menu_id
            )
            # Update menu metadata
            await db.execute("""
                UPDATE meal_menus SET updated_by = $1, is_published = TRUE
                WHERE id = $2
            """, admin["id"], menu_id)
        else:
            # Create new menu
            menu_id = await db.fetchval("""
                INSERT INTO meal_menus (hostel_id, meal_slot_id, date, is_recurring, is_published, created_by, updated_by)
                VALUES ($1, $2, $3, FALSE, TRUE, $4, $4) RETURNING id
            """, body.hostel_id, body.meal_slot_id, body.date, admin["id"])

        # Insert new items
        for sort_order, item_id in enumerate(body.item_ids):
            await db.execute("""
                INSERT INTO meal_menu_items (meal_menu_id, menu_item_id, sort_order)
                VALUES ($1, $2, $3)
            """, menu_id, item_id, sort_order)

    return {"id": menu_id, "message": "Menu saved successfully"}


# ══════════════════════════════════════════════════════════════════════════════
# MEAL SLOTS & HOSTELS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/meal-slots")
async def get_meal_slots(
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Returns all active meal slots."""
    slots = await db.fetch(
        "SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY display_order"
    )
    result = []
    for s in slots:
        result.append({
            "id": s["id"],
            "name": s["name"],
            "display_order": s["display_order"],
            "start_time": s["start_time"].strftime("%I:%M %p"),
            "end_time": s["end_time"].strftime("%I:%M %p"),
            "color_code": s.get("color_code", "#4CAF50"),
        })
    return result


@router.get("/hostels")
async def get_hostels(
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Returns all hostels."""
    hostels = await db.fetch(
        "SELECT * FROM hostels WHERE is_active = TRUE ORDER BY name"
    )
    return [dict(h) for h in hostels]


# ══════════════════════════════════════════════════════════════════════════════
# STAFF MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/staff")
async def get_staff(
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Returns all staff with user email, designation, hostel, permissions."""
    staff = await db.fetch("""
        SELECT s.id, s.user_id, s.first_name, s.last_name, s.phone,
               s.designation, s.can_scan_qr, s.can_edit_menu,
               s.can_view_reports, s.can_manage_staff, s.is_active,
               s.created_at, s.updated_at,
               u.email, u.is_active as user_active,
               h.id as hostel_id, h.name as hostel_name
        FROM staff s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN hostels h ON s.hostel_id = h.id
        ORDER BY s.is_active DESC, s.first_name
    """)
    return [dict(s) for s in staff]


@router.post("/staff", status_code=status.HTTP_201_CREATED)
async def create_staff(
    body: StaffCreate,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Create a new staff account."""
    # Check if email exists
    existing = await db.fetchrow(
        "SELECT id FROM users WHERE email = $1", body.email
    )
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Get staff role id (canteen_staff)
    role = await db.fetchrow(
        "SELECT id FROM roles WHERE role_name = 'canteen_staff'"
    )
    if not role:
        raise HTTPException(status_code=500, detail="Staff role not found in database")

    hashed_password = hash_password(body.password)

    async with db.transaction():
        user_id = await db.fetchval("""
            INSERT INTO users (role_id, email, password_hash)
            VALUES ($1, $2, $3) RETURNING id
        """, role["id"], body.email, hashed_password)

        staff_id = await db.fetchval("""
            INSERT INTO staff (user_id, first_name, last_name, phone, designation,
                               hostel_id, can_scan_qr, can_edit_menu,
                               can_view_reports, can_manage_staff)
            VALUES ($1, $2, $3, $4, $5, $6, TRUE, FALSE, FALSE, FALSE) RETURNING id
        """, user_id, body.first_name, body.last_name, body.phone,
            body.designation, body.hostel_id)

    return {"id": staff_id, "user_id": user_id, "message": "Staff account created"}


@router.put("/staff/{staff_id}")
async def update_staff(
    staff_id: int,
    body: StaffUpdate,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Update staff details and permissions."""
    staff = await db.fetchrow("SELECT id FROM staff WHERE id = $1", staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    updates = []
    params = []
    idx = 1
    for field_name, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field_name} = ${idx}")
        params.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(staff_id)
    query = f"UPDATE staff SET {', '.join(updates)} WHERE id = ${idx}"
    await db.execute(query, *params)
    return {"message": "Staff updated"}


@router.delete("/staff/{staff_id}")
async def deactivate_staff(
    staff_id: int,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Deactivate a staff account (soft delete)."""
    staff = await db.fetchrow(
        "SELECT id, user_id FROM staff WHERE id = $1", staff_id
    )
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    async with db.transaction():
        await db.execute(
            "UPDATE staff SET is_active = FALSE WHERE id = $1", staff_id
        )
        await db.execute(
            "UPDATE users SET is_active = FALSE WHERE id = $1", staff["user_id"]
        )

    return {"message": "Staff account deactivated"}


@router.get("/staff/{staff_id}/scans")
async def get_staff_scans(
    staff_id: int,
    admin: dict = Depends(require_admin),
    db: Connection = Depends(get_db),
):
    """Returns scan history for a specific staff member."""
    staff = await db.fetchrow("SELECT id FROM staff WHERE id = $1", staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    scans = await db.fetch("""
        SELECT sc.id, sc.scan_date, sc.scanned_at, sc.status, sc.failure_reason,
               s.first_name || ' ' || s.last_name AS student_name,
               s.uid AS student_uid,
               ms.name AS meal_slot
        FROM scans sc
        JOIN students s ON sc.student_id = s.id
        JOIN meal_slots ms ON sc.meal_slot_id = ms.id
        WHERE sc.scanned_by = $1
        ORDER BY sc.scanned_at DESC
        LIMIT 50
    """, staff_id)

    return [dict(scan) for scan in scans]
