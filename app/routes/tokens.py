"""QR Scan routes — Task 4"""
from fastapi import APIRouter, Depends, HTTPException, Request
from asyncpg import Connection
from app.dependencies import get_db, require_staff
from app.schemas.bookings import ScanReq, MsgResp
from app.services.qr_service import process_scan
from app.routes.auth import limiter

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

@router.post("/scan")
@limiter.limit("60/minute")
async def scan_qr(request: ScanReq, req: Request, db: Connection = Depends(get_db), staff_user: dict = Depends(require_staff)):
    staff_id = staff_user["staff_id"]
    result = await process_scan(db, request.qr_payload, staff_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    
    return result
