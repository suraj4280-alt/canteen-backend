from pydantic import BaseModel
from typing import List, Optional
from datetime import date, time

class MealSlotResp(BaseModel):
    id: int
    name: str
    start_time: time
    end_time: time
    booking_cutoff_time: time
    cancel_cutoff_time: Optional[time]
    color_code: str
    icon_name: str

class MenuItemResp(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_veg: bool
    exclusive_group: Optional[str]

class MealMenuResp(BaseModel):
    id: int
    slot_id: int
    date: date
    items: List[MenuItemResp]

class TodayResp(BaseModel):
    current_phase: str
    next_meal: str
    cutoff_time: time
    countdown_hours: int
    countdown_minutes: int
