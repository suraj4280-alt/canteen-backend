from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, datetime

class BookingReq(BaseModel):
    date: date
    slot_id: int
    item_ids: List[int] = Field(..., min_length=1)

class SkipReq(BaseModel):
    reason: str = Field(..., min_length=2)

class BookingResp(BaseModel):
    id: int
    student_id: int
    meal_slot_id: int
    date: date
    order_id: Optional[str]
    status_id: int
    qr_token: Optional[str]
    created_at: datetime

class MsgResp(BaseModel):
    message: str
