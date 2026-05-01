from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

class TokenResp(BaseModel):
    booking_id: int
    meal_slot_name: str
    date: date
    qr_payload: str
    expires_at: Optional[datetime]

class ScanReq(BaseModel):
    qr_payload: str

class ScanResp(BaseModel):
    success: bool
    message: str
