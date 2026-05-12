from datetime import datetime, date, timedelta
from asyncpg import Connection
from fastapi import HTTPException, status

async def check_booking_window(db: Connection, meal_date: date, slot_id: int) -> dict:
    """Check if booking window is open for a given meal slot and date.
    
    Returns a dict with:
      - allowed: bool
      - reason: str (if not allowed)
      - window_open: datetime-like description
      - window_close: datetime-like description
    """
    slot = await db.fetchrow("""
        SELECT name, start_time, end_time, booking_open_day_offset
        FROM meal_slots WHERE id = $1
    """, slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Meal slot not found")
    
    settings = await db.fetchrow("SELECT booking_open_time, booking_cutoff_time FROM hostel_settings LIMIT 1")
    if not settings:
        raise HTTPException(status_code=500, detail="Booking settings not configured")
        
    open_time = settings['booking_open_time']
    close_time = settings['booking_cutoff_time']
    day_offset = slot['booking_open_day_offset'] or 0  # -1 = prev day, 0 = same day
    
    today = date.today()
    now_time = datetime.now().time()
    
    # Determine the booking window date
    # day_offset = -1 means booking opens on (meal_date - 1)
    # day_offset = 0 means booking opens on meal_date itself
    booking_window_date = meal_date + timedelta(days=day_offset)
    
    # Meal date must not be in the past
    if meal_date < today:
        return {
            "allowed": False,
            "reason": "Cannot book meals in the past"
        }
    
    # If meal_date is today AND the meal has already ended
    if meal_date == today and now_time > slot['end_time']:
        return {
            "allowed": False,
            "reason": f"{slot['name']} has already ended for today"
        }
    
    # Format times for display
    def fmt_time(t):
        h = t.hour
        m = t.minute
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"
    
    # Check if today is the booking window date
    if today < booking_window_date:
        # Booking window hasn't arrived yet
        if day_offset == -1:
            return {
                "allowed": False,
                "reason": f"Booking opens at {fmt_time(open_time)} the evening before ({booking_window_date.strftime('%d %b')})"
            }
        else:
            return {
                "allowed": False,
                "reason": f"Booking opens at {fmt_time(open_time)} on {booking_window_date.strftime('%d %b')}"
            }
    
    if today == booking_window_date:
        # We are on the correct day for the booking window
        if now_time < open_time:
            return {
                "allowed": False,
                "reason": f"Booking not open yet. Opens at {fmt_time(open_time)}"
            }
        if now_time > close_time:
            return {
                "allowed": False,
                "reason": f"Booking window closed. Was open until {fmt_time(close_time)}"
            }
        # Window is open!
        return {"allowed": True}
    
    # today > booking_window_date: the window day has passed
    if today > booking_window_date:
        return {
            "allowed": False,
            "reason": f"Booking window closed. Was open {fmt_time(open_time)}-{fmt_time(close_time)} on {booking_window_date.strftime('%d %b')}"
        }
    
    return {"allowed": True}


async def is_booking_window_open(db: Connection, meal_date: date, slot_id: int) -> bool:
    """Simple boolean wrapper: returns True if booking is currently allowed."""
    result = await check_booking_window(db, meal_date, slot_id)
    return result["allowed"]


async def is_cutoff_passed(db: Connection, meal_date: date, slot_id: int) -> bool:
    """Backward-compatible wrapper. Returns True if booking is NOT allowed."""
    return not await is_booking_window_open(db, meal_date, slot_id)


async def is_cancel_cutoff_passed(db: Connection, meal_date: date, slot_id: int, hostel_id: int = None) -> bool:
    """Cancel cutoff uses the same window logic as booking cutoff.
    Uses cancel_cutoff_time if set, otherwise falls back to booking_cutoff_time."""
    slot = await db.fetchrow("""
        SELECT cancel_cutoff_time, booking_open_day_offset
        FROM meal_slots WHERE id = $1
    """, slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Meal slot not found")
        
    settings = await db.fetchrow("SELECT booking_open_time, booking_cutoff_time FROM hostel_settings LIMIT 1")
    if not settings:
        raise HTTPException(status_code=500, detail="Booking settings not configured")
    
    # Use cancel_cutoff_time if set, otherwise fall back to global booking_cutoff_time
    close_time = slot['cancel_cutoff_time'] or settings['booking_cutoff_time']
    open_time = settings['booking_open_time']
    day_offset = slot['booking_open_day_offset'] or 0
    
    today = date.today()
    now_time = datetime.now().time()
    booking_window_date = meal_date + timedelta(days=day_offset)
    
    if meal_date < today:
        return True
    
    if today < booking_window_date:
        return False  # Window hasn't opened yet, so cancel isn't needed
    
    if today == booking_window_date:
        return now_time > close_time
    
    # Past the window date
    return True


async def get_booking_window_days(db: Connection, hostel_id: int) -> int:
    """Read booking_window_days from hostel_settings."""
    row = await db.fetchval(
        "SELECT booking_window_days FROM hostel_settings WHERE hostel_id = $1",
        hostel_id
    )
    return row or 7

async def validate_menu_items(db: Connection, menu_id: int, menu_items: list[int]) -> None:
    if not menu_items:
        return
        
    query = """
        SELECT menu_item_id, exclusive_group 
        FROM meal_menu_items 
        WHERE meal_menu_id = $1 AND menu_item_id = ANY($2::int[])
    """
    items = await db.fetch(query, menu_id, menu_items)
    
    if len(items) != len(menu_items):
        raise HTTPException(status_code=400, detail="One or more items are invalid or unavailable for this menu")
    
    groups_seen = set()
    for item in items:
        group = item['exclusive_group']
        if group:
            if group in groups_seen:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail=f"Cannot select multiple items from exclusive group: {group}"
                )
            groups_seen.add(group)

async def find_or_create_meal_menu(db: Connection, hostel_id: int, slot_id: int, target_date: date) -> int:
    menu_id = await db.fetchval("""
        SELECT id FROM meal_menus 
        WHERE meal_slot_id = $1 AND hostel_id = $2 AND date = $3 AND is_active = TRUE
    """, slot_id, hostel_id, target_date)
    
    if menu_id:
        return menu_id
        
    menu_id = await db.fetchval("""
        SELECT id FROM meal_menus 
        WHERE meal_slot_id = $1 AND hostel_id = $2 AND is_recurring = TRUE AND is_active = TRUE
    """, slot_id, hostel_id)
    
    if not menu_id:
        raise HTTPException(status_code=404, detail="No menu available for this meal slot")
        
    return menu_id

async def check_duplicate_booking(db: Connection, student_id: int, slot_id: int, target_date: date) -> None:
    existing = await db.fetchval("""
        SELECT b.id FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.student_id = $1 AND b.meal_slot_id = $2 AND b.date = $3 
          AND bs.is_terminal = FALSE
    """, student_id, slot_id, target_date)
    
    if existing:
        raise HTTPException(status_code=400, detail="Active booking already exists for this slot and date")


MAX_CANCEL_COUNT = 3

async def check_cancel_limit(db: Connection, student_id: int, slot_id: int, target_date: date) -> None:
    """Block re-booking if student has cancelled this slot 3+ times on this date."""
    row = await db.fetchrow("""
        SELECT cancel_count FROM bookings
        WHERE student_id = $1 AND meal_slot_id = $2 AND date = $3
    """, student_id, slot_id, target_date)
    
    if row and row['cancel_count'] >= MAX_CANCEL_COUNT:
        raise HTTPException(
            status_code=400,
            detail="You have reached the maximum cancellation limit for this meal. Booking is no longer available for this slot."
        )


async def increment_cancel_count(db: Connection, booking_id: int) -> int:
    """Increment cancel_count for a booking and return the new count."""
    new_count = await db.fetchval("""
        UPDATE bookings 
        SET cancel_count = COALESCE(cancel_count, 0) + 1
        WHERE id = $1
        RETURNING cancel_count
    """, booking_id)
    return new_count or 0
