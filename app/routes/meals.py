from fastapi import APIRouter, Depends, HTTPException
from asyncpg import Connection
from datetime import date, datetime
from typing import List
from app.dependencies import get_db, get_current_student, get_current_user, require_staff
from app.schemas.meals import MealSlotResp, MealMenuResp, TodayResp
from app.services.booking_service import find_or_create_meal_menu

router = APIRouter(prefix="/api/meals", tags=["meals"])

@router.get("/slots", response_model=List[MealSlotResp])
async def get_slots(db: Connection = Depends(get_db), current_user: dict = Depends(get_current_user)):
    slots = await db.fetch("SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY display_order")
    return [dict(s) for s in slots]

@router.get("/menu", response_model=MealMenuResp)
async def get_menu(date: date, slot_id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    hostel_id = student["hostel_id"]
    if not hostel_id:
        raise HTTPException(status_code=400, detail="Student is not assigned to any hostel")
        
    menu_id = await find_or_create_meal_menu(db, hostel_id, slot_id, date)
    
    query = """
        SELECT mi.*, mmi.exclusive_group 
        FROM menu_items mi
        JOIN meal_menu_items mmi ON mi.id = mmi.menu_item_id
        WHERE mmi.meal_menu_id = $1 AND mi.is_active = TRUE
    """
    items = await db.fetch(query, menu_id)
    
    return {
        "id": menu_id,
        "slot_id": slot_id,
        "date": date,
        "items": [dict(i) for i in items]
    }

@router.get("/today", response_model=TodayResp)
async def get_today(db: Connection = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Task 8: Real countdown to next meal cutoff based on server time."""
    now = datetime.now()
    current_time = now.time()
    
    slots = await db.fetch("SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY start_time")
    
    current_phase = "Unknown"
    next_meal = "Unknown"
    cutoff = None
    countdown_hours = 0
    countdown_minutes = 0
    
    # Check if we're currently in a meal slot
    for slot in slots:
        if slot['start_time'] <= current_time <= slot['end_time']:
            current_phase = slot['name']
            cutoff = slot['booking_cutoff_time']
            break
    
    # If not in any slot, find the next upcoming slot
    if current_phase == "Unknown":
        for slot in slots:
            if current_time < slot['start_time']:
                next_meal = slot['name']
                cutoff = slot['booking_cutoff_time']
                break
    
    # Calculate countdown to cutoff
    if cutoff:
        cutoff_dt = datetime.combine(now.date(), cutoff)
        if cutoff_dt > now:
            diff = cutoff_dt - now
            total_minutes = int(diff.total_seconds() // 60)
            countdown_hours = total_minutes // 60
            countdown_minutes = total_minutes % 60
    
    if not cutoff and slots:
        cutoff = slots[0]['booking_cutoff_time']
        
    return {
        "current_phase": current_phase,
        "next_meal": next_meal,
        "cutoff_time": cutoff or current_time,
        "countdown_hours": countdown_hours,
        "countdown_minutes": countdown_minutes,
    }

@router.get("/today/stats")
async def get_today_stats(db: Connection = Depends(get_db), staff: dict = Depends(require_staff)):
    """Staff-only: Get today's booking and scan counts per meal slot."""
    today = date.today()
    now_time = datetime.now().time()
    
    slots = await db.fetch("SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY display_order")
    
    result = []
    for slot in slots:
        # Count total bookings for this slot today (only active/booked + used)
        total_booked = await db.fetchval("""
            SELECT COUNT(*) FROM bookings b
            JOIN booking_status bs ON b.status_id = bs.id
            WHERE b.meal_slot_id = $1 AND b.date = $2
              AND bs.status_name IN ('booked', 'used')
        """, slot['id'], today)
        
        # Count scanned/used bookings
        total_scanned = await db.fetchval("""
            SELECT COUNT(*) FROM bookings b
            JOIN booking_status bs ON b.status_id = bs.id
            WHERE b.meal_slot_id = $1 AND b.date = $2
              AND bs.status_name = 'used'
        """, slot['id'], today)
        
        # Determine slot status
        if now_time > slot['end_time']:
            status = "past"
        elif now_time >= slot['start_time']:
            status = "active"
        else:
            status = "upcoming"
        
        result.append({
            "slot_id": slot['id'],
            "slot_name": slot['name'],
            "start_time": slot['start_time'].strftime('%I:%M %p'),
            "end_time": slot['end_time'].strftime('%I:%M %p'),
            "total_booked": total_booked or 0,
            "total_scanned": total_scanned or 0,
            "remaining": (total_booked or 0) - (total_scanned or 0),
            "status": status,
            "color_code": slot.get('color_code', '#4CAF50'),
        })
    
    return {"date": str(today), "slots": result}
