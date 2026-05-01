from fastapi import APIRouter, Depends, HTTPException
from asyncpg import Connection
from datetime import date, datetime
from typing import List
from app.dependencies import get_db, get_current_student, get_current_user
from app.schemas.meals import MealSlotResp, MealMenuResp, TodayResp

router = APIRouter(prefix="/api/meals", tags=["meals"])

@router.get("/slots", response_model=List[MealSlotResp])
async def get_slots(db: Connection = Depends(get_db), current_user: dict = Depends(get_current_user)):
    slots = await db.fetch("SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY display_order")
    return [dict(s) for s in slots]

@router.get("/menu", response_model=MealMenuResp)
async def get_menu(date: date, slot_id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    from app.services.booking_service import find_or_create_meal_menu
    
    hostel_id = student["hostel_id"]
    if not hostel_id:
        raise HTTPException(status_code=400, detail="Student is not assigned to any hostel")
        
    menu_id = await find_or_create_meal_menu(db, hostel_id, slot_id, date)
    
    query = """
        SELECT mi.* 
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
    now = datetime.now()
    current_time = now.time()
    
    slots = await db.fetch("SELECT * FROM meal_slots WHERE is_active = TRUE ORDER BY start_time")
    
    current_phase = "Unknown"
    next_meal = "Unknown"
    cutoff = None
    
    for slot in slots:
        if slot['start_time'] <= current_time <= slot['end_time']:
            current_phase = slot['name']
            cutoff = slot['booking_cutoff_time']
            break
            
    if current_phase == "Unknown":
        for slot in slots:
            if current_time < slot['start_time']:
                next_meal = slot['name']
                cutoff = slot['booking_cutoff_time']
                break
                
    if not cutoff and slots:
        cutoff = slots[0]['booking_cutoff_time']
            
    return {
        "current_phase": current_phase,
        "next_meal": next_meal,
        "cutoff_time": cutoff or current_time,
        "countdown_hours": 0,  # TODO: implement actual countdown logic
        "countdown_minutes": 0 # TODO: implement actual countdown logic
    }
