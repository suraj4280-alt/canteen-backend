"""QR Scan routes — Task 4"""
from fastapi import APIRouter, Depends, HTTPException
from asyncpg import Connection
from app.dependencies import get_db, require_staff
from app.schemas.bookings import ScanReq, MsgResp
from app.services.qr_service import process_scan

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

@router.post("/scan", response_model=MsgResp)
async def scan_qr(request: ScanReq, db: Connection = Depends(get_db), staff_user: dict = Depends(require_staff)):
    staff_id = staff_user["staff_id"]
    await process_scan(db, request.qr_payload, staff_id)
    return MsgResp(message="Booking scanned and marked as used")
