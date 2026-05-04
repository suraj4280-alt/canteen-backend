from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, datetime, time

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
    order_id: Optional[str] = None
    status_id: int
    qr_token: Optional[str] = None
    created_at: datetime

class BookingHistoryResp(BookingResp):
    """Extended response with JOINed slot and status fields for history/list views."""
    slot_name: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status_name: Optional[str] = None
    status_label: Optional[str] = None
    skip_reason: Optional[str] = None
    meal_menu_id: Optional[int] = None

class MsgResp(BaseModel):
    message: str

class QRResp(BaseModel):
    booking_id: int
    qr_token: str
    valid_from: time
    valid_until: time

class PaginatedBookingsResp(BaseModel):
    items: List[BookingHistoryResp]
    total: int
    page: int
    size: int

class UpcomingBookingResp(BaseModel):
    id: int
    date: date
    status_id: int
    status_name: str
    slot_name: str
    start_time: time
    end_time: time
    order_id: Optional[str] = None
    item_ids: List[int] = []

class ScanReq(BaseModel):
    qr_payload: str
