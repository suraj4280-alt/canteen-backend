from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime

class LeaveReq(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=3)
    reason_category: str = "home_visit"

class LeaveResp(BaseModel):
    id: int
    student_id: int
    start_date: date
    end_date: date
    reason: str
    reason_category: str
    is_approved: bool
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
