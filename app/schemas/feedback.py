from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class FeedbackReq(BaseModel):
    booking_id: int
    food_rating: int = Field(..., ge=1, le=5)
    service_rating: int = Field(..., ge=1, le=5)
    cleanliness_rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    tag_ids: Optional[List[int]] = None

class FeedbackResp(BaseModel):
    id: int
    booking_id: int
    food_rating: int
    service_rating: int
    cleanliness_rating: int
    comment: Optional[str] = None
    created_at: datetime

class FeedbackTagResp(BaseModel):
    id: int
    tag_name: str
    display_label: str
    color_code: Optional[str] = None
    icon_name: Optional[str] = None
