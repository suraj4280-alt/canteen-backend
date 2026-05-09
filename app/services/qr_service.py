"""QR service — process_scan validates a QR token UUID and marks the booking as used.
Returns a detailed result dict for the staff app to display."""
from datetime import datetime, timezone, date
from uuid import UUID
from asyncpg import Connection
from fastapi import HTTPException


async def process_scan(db: Connection, qr_payload: str, scanned_by: int) -> dict:
    """Validate a QR token (UUID) and mark the booking as used.

    Returns a dict with success/failure info and student details.
    The staff app uses this to show specific result screens.
    """
    # Validate that the payload is a proper UUID
    try:
        token_uuid = UUID(qr_payload.strip())
    except (ValueError, AttributeError):
        return {"success": False, "reason": "invalid_qr", "detail": "Invalid QR code format"}

    # Look up booking by qr_token with full student details
    query = """
        SELECT b.id, b.student_id, b.meal_slot_id, b.date, b.order_id,
               b.status_id, b.qr_token, b.qr_expires_at, b.used_at,
               s.uid, s.first_name, s.last_name, s.room_number,
               s.dietary_preference,
               ms.name as slot_name, ms.start_time, ms.end_time,
               h.name as hostel_name,
               bs.status_name
        FROM bookings b
        JOIN students s ON b.student_id = s.id
        JOIN meal_slots ms ON b.meal_slot_id = ms.id
        LEFT JOIN hostels h ON s.hostel_id = h.id
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.qr_token = $1
    """
    booking = await db.fetchrow(query, token_uuid)
    if not booking:
        return {"success": False, "reason": "invalid_qr", "detail": "Booking not found for this QR token"}

    # Verify the booking is for today
    today = date.today()
    if booking['date'] != today:
        return {
            "success": False,
            "reason": "wrong_date",
            "detail": f"This QR is for {booking['date'].strftime('%d %b %Y')}, not today",
            "correct_date": str(booking['date']),
            "slot_name": booking['slot_name'],
        }

    # Check if already scanned/used
    if booking['status_name'] == 'used':
        # Find the scan time
        scan_record = await db.fetchrow(
            "SELECT created_at FROM scans WHERE booking_id = $1 AND status = 'success' ORDER BY created_at DESC LIMIT 1",
            booking['id']
        )
        scanned_at = scan_record['created_at'].strftime('%I:%M %p') if scan_record else 'earlier'
        return {
            "success": False,
            "reason": "already_scanned",
            "detail": f"This meal was already served at {scanned_at}",
            "scanned_at": scanned_at,
            "student_name": f"{booking['first_name']} {booking['last_name']}",
            "uid": booking['uid'],
            "slot_name": booking['slot_name'],
        }

    # Check booking is in 'booked' state
    if booking['status_name'] != 'booked':
        return {
            "success": False,
            "reason": "invalid_status",
            "detail": f"Booking status is '{booking['status_name']}', not 'booked'",
            "status": booking['status_name'],
            "student_name": f"{booking['first_name']} {booking['last_name']}",
        }

    # Check QR expiry if set
    expires_at = booking.get('qr_expires_at')
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return {
                "success": False,
                "reason": "expired",
                "detail": "QR token has expired",
                "slot_name": booking['slot_name'],
            }

    # Verify the meal time window
    now_time = datetime.now().time()
    if now_time < booking['start_time']:
        return {
            "success": False,
            "reason": "wrong_slot",
            "detail": f"{booking['slot_name']} hasn't started yet (starts at {booking['start_time'].strftime('%I:%M %p')})",
            "correct_slot": booking['slot_name'],
            "start_time": booking['start_time'].strftime('%I:%M %p'),
        }
    if now_time > booking['end_time']:
        return {
            "success": False,
            "reason": "expired",
            "detail": f"{booking['slot_name']} ended at {booking['end_time'].strftime('%I:%M %p')}",
            "slot_name": booking['slot_name'],
            "end_time": booking['end_time'].strftime('%I:%M %p'),
        }

    # All checks passed — mark as used atomically
    async with db.transaction():
        # Lock the booking row to prevent race conditions
        locked = await db.fetchrow(
            "SELECT id, status_id FROM bookings WHERE id = $1 FOR UPDATE",
            booking['id']
        )

        used_status = await db.fetchval(
            "SELECT id FROM booking_status WHERE status_name = 'used'"
        )

        # Double-check after lock
        if locked['status_id'] == used_status:
            return {
                "success": False,
                "reason": "already_scanned",
                "detail": "Booking was scanned by another staff member just now",
            }

        # Check for existing successful scan
        existing = await db.fetchval(
            "SELECT id FROM scans WHERE booking_id = $1 AND status = 'success'",
            booking['id']
        )
        if existing:
            return {
                "success": False,
                "reason": "already_scanned",
                "detail": "Booking has already been scanned",
            }

        # Insert scan record
        await db.execute(
            """
            INSERT INTO scans (booking_id, student_id, meal_slot_id, scan_date,
                              scanned_by, qr_token, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'success')
            """,
            booking['id'], booking['student_id'], booking['meal_slot_id'],
            booking['date'], scanned_by, booking['qr_token']
        )

        # Update booking status to 'used'
        await db.execute(
            "UPDATE bookings SET status_id = $1, used_at = NOW() WHERE id = $2",
            used_status, booking['id']
        )

    return {
        "success": True,
        "student_name": f"{booking['first_name']} {booking['last_name']}",
        "uid": booking['uid'],
        "hostel": booking['hostel_name'] or "N/A",
        "room_number": booking['room_number'] or "N/A",
        "dietary_preference": booking['dietary_preference'] or "veg",
        "slot_name": booking['slot_name'],
        "order_id": booking['order_id'] or "",
        "scan_time": datetime.now().strftime('%I:%M %p'),
    }
