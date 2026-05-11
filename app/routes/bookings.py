from fastapi import APIRouter, Depends, HTTPException, status, Query
from asyncpg import Connection
import asyncpg.exceptions
from app.dependencies import get_db, get_current_student
from datetime import datetime, date as date_type
from app.schemas.bookings import BookingReq, SkipReq, BookingResp, MsgResp, QRResp, PaginatedBookingsResp, UpcomingBookingResp
from app.services.booking_service import (
    is_cutoff_passed, is_cancel_cutoff_passed, validate_menu_items,
    find_or_create_meal_menu, check_duplicate_booking, check_booking_window
)

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

@router.get("", response_model=PaginatedBookingsResp)
async def get_bookings(
    page: int = 1, 
    size: int = 10, 
    db: Connection = Depends(get_db), 
    student: dict = Depends(get_current_student)
):
    student_id = student["student_id"]
    offset = (page - 1) * size
    
    # Bulk-mark missed bookings in one query before fetching
    await db.execute("""
        UPDATE bookings 
        SET status_id = (SELECT id FROM booking_status WHERE status_name = 'missed')
        WHERE student_id = $1 
          AND status_id = (SELECT id FROM booking_status WHERE status_name = 'booked')
          AND (
              date < CURRENT_DATE 
              OR (date = CURRENT_DATE AND meal_slot_id IN (
                  SELECT id FROM meal_slots WHERE end_time < CURRENT_TIME
              ))
          )
    """, student_id)
    
    total = await db.fetchval("SELECT COUNT(*) FROM bookings WHERE student_id = $1", student_id)
    
    query = """
        SELECT b.*, ms.name as slot_name, ms.start_time, ms.end_time,
               bs.status_name, bs.display_label as status_label
        FROM bookings b
        JOIN meal_slots ms ON b.meal_slot_id = ms.id
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.student_id = $1 
        ORDER BY b.date DESC, b.created_at DESC 
        LIMIT $2 OFFSET $3
    """
    rows = await db.fetch(query, student_id, size, offset)
    
    items = []
    for r in rows:
        d = dict(r)
        d['qr_token'] = str(d['qr_token']) if d.get('qr_token') else None
        items.append(d)
        
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size
    }

@router.get("/upcoming", response_model=list[UpcomingBookingResp])
async def get_upcoming_bookings(db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    query = """
        SELECT b.id, b.date, b.status_id, bs.status_name, b.order_id,
               ms.name as slot_name, ms.start_time, ms.end_time,
               COALESCE(
                   (SELECT array_agg(menu_item_id) FROM booking_items WHERE booking_id = b.id),
                   '{}'::int[]
               ) as item_ids
        FROM bookings b
        JOIN meal_slots ms ON b.meal_slot_id = ms.id
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.student_id = $1 
          AND b.date >= CURRENT_DATE 
          AND bs.status_name != 'cancelled'
        ORDER BY b.date ASC, ms.start_time ASC
    """
    rows = await db.fetch(query, student_id)
    
    results = []
    for r in rows:
        d = dict(r)
        d['item_ids'] = list(d['item_ids'])
        results.append(d)
        
    return results

@router.get("/status", response_model=dict)
async def get_booking_status(date: date_type, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    query = """
        SELECT b.meal_slot_id, bs.status_name
        FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.student_id = $1 AND b.date = $2
    """
    rows = await db.fetch(query, student_id, date)
    # The frontend expects mapping from slotId -> status
    # Note: frontend slot indexing might be 1-based or 0-based.
    # The requirement says {"1": "confirmed", "2": "skipped"} where 1 is slotId.
    # I will return slot_id as string keys.
    # I will map 'booked' to 'confirmed' for consistency with the frontend expectations.
    
    result = {}
    for r in rows:
        status = r["status_name"]
        if status == "booked":
            status = "confirmed"
        result[str(r["meal_slot_id"])] = status
        
    return result

@router.post("", response_model=BookingResp, status_code=status.HTTP_201_CREATED)
async def create_booking(request: BookingReq, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    window = await check_booking_window(db, request.date, request.slot_id)
    if not window["allowed"]:
        raise HTTPException(status_code=400, detail=window["reason"])
        
    await check_duplicate_booking(db, student_id, request.slot_id, request.date)
    
    hostel_id = student["hostel_id"]
    if not hostel_id:
        raise HTTPException(status_code=400, detail="Student is not assigned to any hostel")
        
    menu_id = await find_or_create_meal_menu(db, hostel_id, request.slot_id, request.date)
    
    # Enforce max_bookings capacity on menu
    menu_capacity = await db.fetchrow(
        "SELECT max_bookings, bookings_count FROM meal_menus WHERE id = $1", menu_id
    )
    if menu_capacity and menu_capacity['bookings_count'] >= menu_capacity['max_bookings']:
        raise HTTPException(status_code=400, detail="This meal is fully booked. No more slots available.")
    
    await validate_menu_items(db, menu_id, request.item_ids)
    
    async with db.transaction():
        status_id = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'booked'")
        
        # We use ON CONFLICT to overwrite a cancelled booking with the new booking details.
        booking_id = await db.fetchval(
            """
            INSERT INTO bookings (student_id, meal_slot_id, meal_menu_id, date, status_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (student_id, meal_slot_id, date) 
            DO UPDATE SET 
                status_id = EXCLUDED.status_id,
                meal_menu_id = EXCLUDED.meal_menu_id,
                qr_token = uuid_generate_v4()
            RETURNING id
            """,
            student_id, request.slot_id, menu_id, request.date, status_id
        )
        
        # Clear old items in case this was an update to an existing cancelled booking
        await db.execute("DELETE FROM booking_items WHERE booking_id = $1", booking_id)
        for item_id in request.item_ids:
            await db.execute(
                "INSERT INTO booking_items (booking_id, menu_item_id) VALUES ($1, $2)",
                booking_id, item_id
            )
            
        booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1", booking_id)
        
    booking_dict = dict(booking)
    booking_dict['qr_token'] = str(booking['qr_token']) if booking.get('qr_token') else None
    return booking_dict

@router.get("/stats", response_model=dict)
async def get_booking_stats(db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    query = """
        SELECT 
            COUNT(*) as total_bookings,
            COUNT(*) FILTER (WHERE bs.status_name = 'skipped') as skipped,
            COUNT(*) FILTER (WHERE bs.status_name = 'used') as consumed,
            COUNT(*) FILTER (WHERE bs.status_name = 'cancelled') as cancelled,
            COUNT(*) FILTER (WHERE bs.status_name = 'missed') as missed,
            COUNT(*) FILTER (WHERE bs.status_name = 'booked') as active
        FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.student_id = $1
    """
    row = await db.fetchrow(query, student_id)
    return {
        "total_bookings": row["total_bookings"],
        "skipped": row["skipped"],
        "consumed": row["consumed"],
        "cancelled": row["cancelled"],
        "missed": row["missed"],
        "active": row["active"]
    }

@router.get("/{id}", response_model=BookingResp)
async def get_booking(id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    booking_dict = dict(booking)
    booking_dict['qr_token'] = str(booking['qr_token']) if booking.get('qr_token') else None
    return booking_dict

@router.get("/{id}/qr", response_model=QRResp)
async def get_booking_qr(id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    booking = await db.fetchrow(
        """
        SELECT b.*, ms.start_time, ms.end_time 
        FROM bookings b
        JOIN meal_slots ms ON b.meal_slot_id = ms.id
        WHERE b.id = $1 AND b.student_id = $2
        """, 
        id, student_id
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    today = datetime.now().date()
    now_time = datetime.now().time()
    
    if booking['date'] > today:
        raise HTTPException(status_code=400, detail="QR not available yet")
    elif booking['date'] < today:
        raise HTTPException(status_code=400, detail="Meal time expired")
    elif now_time < booking['start_time']:
        raise HTTPException(status_code=400, detail="QR not available yet")
    elif now_time > booking['end_time']:
        raise HTTPException(status_code=400, detail="Meal time expired")
        
    qr_token = booking.get('qr_token')
    if not qr_token:
        qr_token = await db.fetchval(
            "UPDATE bookings SET qr_token = gen_random_uuid() WHERE id = $1 RETURNING qr_token",
            id
        )
        
    return QRResp(
        booking_id=id,
        qr_token=str(qr_token),
        valid_from=booking['start_time'],
        valid_until=booking['end_time']
    )

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
    hostel_id = student.get("hostel_id")
    
    booking = await db.fetchrow("SELECT * FROM bookings WHERE id = $1 AND student_id = $2", id, student_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Use cancel-specific cutoff (falls back to booking cutoff if not set)
    if await is_cancel_cutoff_passed(db, booking['date'], booking['meal_slot_id'], hostel_id):
        raise HTTPException(status_code=400, detail="Cannot cancel after cancellation cutoff time")
        
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
