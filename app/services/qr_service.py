from datetime import datetime, timezone
from asyncpg import Connection
from fastapi import HTTPException

async def generate_qr_payload(db: Connection, booking_id: int) -> dict:
    query = """
        SELECT b.id, b.date, b.order_id, b.qr_expires_at, b.meal_slot_id, s.uid, ms.name as slot_name
        FROM bookings b
        JOIN students s ON b.student_id = s.id
        JOIN meal_slots ms ON b.meal_slot_id = ms.id
        WHERE b.id = $1
    """
    row = await db.fetchrow(query, booking_id)
    if not row:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    return {
        "booking_id": row['id'],
        "meal_slot_name": row['slot_name'],
        "date": row['date'],
        "qr_payload": f"{row['uid']}|{row['date']}|{row['meal_slot_id']}|{row['order_id']}",
        "expires_at": row['qr_expires_at']
    }

async def validate_qr_token(db: Connection, qr_payload: str) -> dict:
    parts = qr_payload.split('|')
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="Invalid QR payload format")
        
    uid, meal_date_str, slot_str, order_id = parts
    
    query = """
        SELECT b.*, ms.name as slot_name
        FROM bookings b
        JOIN students s ON b.student_id = s.id
        JOIN meal_slots ms ON b.meal_slot_id = ms.id
        WHERE b.order_id = $1 AND s.uid = $2
    """
    booking = await db.fetchrow(query, order_id, uid)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found for this QR token")

    if str(booking['date']) != meal_date_str:
        raise HTTPException(status_code=400, detail="QR token date mismatch")
        
    if str(booking['meal_slot_id']) != slot_str:
        raise HTTPException(status_code=400, detail="QR token slot mismatch")

    expires_at = booking['qr_expires_at']
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=400, detail="QR token is expired")

    booked_status = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'booked'")
    if booking['status_id'] != booked_status:
        raise HTTPException(status_code=400, detail="Booking is not in 'booked' state")

    return dict(booking)

async def process_scan(db: Connection, qr_payload: str, scanned_by: int) -> None:
    booking = await validate_qr_token(db, qr_payload)
    
    async with db.transaction():
        # Lock the booking row to prevent race conditions during concurrent scans
        locked_booking = await db.fetchrow("SELECT id, status_id FROM bookings WHERE id = $1 FOR UPDATE", booking['id'])
        
        used_status = await db.fetchval("SELECT id FROM booking_status WHERE status_name = 'used'")
        if locked_booking['status_id'] == used_status:
            raise HTTPException(status_code=400, detail="Booking has already been scanned")
            
        existing_scan = await db.fetchval("SELECT id FROM scans WHERE booking_id = $1 AND status = 'success'", booking['id'])
        if existing_scan:
            raise HTTPException(status_code=400, detail="Booking has already been scanned")

        await db.execute(
            """
            INSERT INTO scans (booking_id, student_id, meal_slot_id, scan_date, scanned_by, qr_token, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            booking['id'], booking['student_id'], booking['meal_slot_id'], booking['date'],
            scanned_by, booking['qr_token'], 'success'
        )
        
        await db.execute(
            "UPDATE bookings SET status_id = $1 WHERE id = $2",
            used_status, booking['id']
        )
