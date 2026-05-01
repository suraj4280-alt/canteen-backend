from fastapi import APIRouter, Depends, HTTPException, status
from asyncpg import Connection
from app.dependencies import get_db, get_current_student
from app.schemas.bookings import BookingReq, SkipReq, BookingResp, MsgResp
from app.services.booking_service import (
    is_cutoff_passed, validate_menu_items,
    find_or_create_meal_menu, check_duplicate_booking
)

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

@router.post("", response_model=BookingResp, status_code=status.HTTP_201_CREATED)
async def create_booking(request: BookingReq, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    if await is_cutoff_passed(db, request.date, request.slot_id):
        raise HTTPException(status_code=400, detail="Booking cutoff time has passed")
        
    await check_duplicate_booking(db, student_id, request.slot_id, request.date)
    
    hostel_id = student["hostel_id"]
    if not hostel_id:
        raise HTTPException(status_code=400, detail="Student is not assigned to any hostel")
        
    menu_id = await find_or_create_meal_menu(db, hostel_id, request.slot_id, request.date)
    
    await validate_menu_items(db, menu_id, request.item_ids)
    
    async with db.transaction():
        status_id = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'booked'")
        
        booking_id = await db.fetchval(
            """
            INSERT INTO bookings (student_id, meal_slot_id, meal_menu_id, date, status_id)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
            """,
            student_id, request.slot_id, menu_id, request.date, status_id
        )
        
        for item_id in request.item_ids:
            await db.execute(
                "INSERT INTO booking_items (booking_id, menu_item_id) VALUES ($1, $2)",
                booking_id, item_id
            )
            
        booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1", booking_id)
        
    booking_dict = dict(booking)
    booking_dict['qr_token'] = str(booking['qr_token']) if booking.get('qr_token') else None
    return booking_dict

@router.get("/{id}", response_model=BookingResp)
async def get_booking(id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    booking_dict = dict(booking)
    booking_dict['qr_token'] = str(booking['qr_token']) if booking.get('qr_token') else None
    return booking_dict

@router.put("/{id}", response_model=MsgResp)
async def update_booking(id: int, request: BookingReq, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    if await is_cutoff_passed(db, booking['date'], booking['meal_slot_id']):
        raise HTTPException(status_code=400, detail="Cannot update after cutoff time")
        
    await validate_menu_items(db, booking['meal_menu_id'], request.item_ids)
    
    async with db.transaction():
        await db.execute("DELETE FROM booking_items WHERE booking_id = $1", id)
        for item_id in request.item_ids:
            await db.execute(
                "INSERT INTO booking_items (booking_id, menu_item_id) VALUES ($1, $2)",
                id, item_id
            )
    return MsgResp(message="Booking updated successfully")

@router.delete("/{id}", response_model=MsgResp)
async def cancel_booking(id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    if await is_cutoff_passed(db, booking['date'], booking['meal_slot_id']):
        raise HTTPException(status_code=400, detail="Cannot cancel after cutoff time")
        
    status_id = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'cancelled'")
    await db.execute("UPDATE bookings SET status_id = $1 WHERE id = $2", status_id, id)
    return MsgResp(message="Booking cancelled successfully")

@router.post("/{id}/skip", response_model=MsgResp)
async def skip_booking(id: int, request: SkipReq, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    if await is_cutoff_passed(db, booking['date'], booking['meal_slot_id']):
        raise HTTPException(status_code=400, detail="Cannot skip after cutoff time")
        
    status_id = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'skipped'")
    await db.execute(
        "UPDATE bookings SET status_id = $1, skip_reason = $2 WHERE id = $3", 
        status_id, request.reason, id
    )
    return MsgResp(message="Meal skipped successfully")

@router.delete("/{id}/skip", response_model=MsgResp)
async def undo_skip_booking(id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    if await is_cutoff_passed(db, booking['date'], booking['meal_slot_id']):
        raise HTTPException(status_code=400, detail="Cannot undo skip after cutoff time")
        
    status_id = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'booked'")
    await db.execute(
        "UPDATE bookings SET status_id = $1, skip_reason = NULL WHERE id = $2", 
        status_id, id
    )
    return MsgResp(message="Skip undone successfully")
