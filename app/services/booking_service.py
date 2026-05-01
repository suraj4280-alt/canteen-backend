from datetime import datetime, date
from asyncpg import Connection
from fastapi import HTTPException, status

async def is_cutoff_passed(db: Connection, meal_date: date, slot_id: int) -> bool:
    slot = await db.fetchrow("SELECT booking_cutoff_time FROM meal_slots WHERE id = $1", slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Meal slot not found")
        
    cutoff_time = slot['booking_cutoff_time']
    today = date.today()
    now_time = datetime.now().time()
    
    if meal_date < today:
        return True
    if meal_date > today:
        return False
        
    return now_time > cutoff_time

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
        SELECT id FROM bookings 
        WHERE student_id = $1 AND meal_slot_id = $2 AND date = $3 AND status_id != (SELECT id FROM booking_status WHERE status_name = 'cancelled')
    """, student_id, slot_id, target_date)
    
    if existing:
        raise HTTPException(status_code=400, detail="Active booking already exists for this slot and date")
