from fastapi import APIRouter, Depends, HTTPException
from typing import List
from asyncpg import Connection
from app.dependencies import get_db, get_current_student, require_staff
from app.schemas.tokens import TokenResp, ScanReq, ScanResp
from app.services.qr_service import generate_qr_payload, process_scan

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

@router.get("/active", response_model=List[TokenResp])
async def get_active_tokens(db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    query = """
        SELECT id FROM bookings
        WHERE student_id = $1 AND date = CURRENT_DATE 
          AND status_id = (SELECT id FROM booking_status WHERE status_name = 'booked')
    """
    bookings = await db.fetch(query, student_id)
    return [await generate_qr_payload(db, b['id']) for b in bookings]

@router.get("/upcoming", response_model=List[TokenResp])
async def get_upcoming_tokens(db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    query = """
        SELECT id FROM bookings
        WHERE student_id = $1 AND date > CURRENT_DATE 
          AND status_id = (SELECT id FROM booking_status WHERE status_name = 'booked')
        ORDER BY date, meal_slot_id
    """
    bookings = await db.fetch(query, student_id)
    return [await generate_qr_payload(db, b['id']) for b in bookings]

@router.get("/qr-data/{booking_id}", response_model=TokenResp)
async def get_qr_data(booking_id: int, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    owner = await db.fetchval("SELECT student_id FROM bookings WHERE id = $1", booking_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Booking not found")
    if owner != student_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this QR code")
        
    return await generate_qr_payload(db, booking_id)

@router.post("/scan", response_model=ScanResp)
async def scan_token(request: ScanReq, db: Connection = Depends(get_db), staff: dict = Depends(require_staff)):
    staff_id = staff["staff_id"]
    await process_scan(db, request.qr_payload, staff_id)
    return {"success": True, "message": "Meal marked as used successfully"}
