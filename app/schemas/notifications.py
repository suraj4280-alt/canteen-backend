from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class NotificationResp(BaseModel):
    id: int
    title: str
    message: str
    type: Optional[str] = None
    priority: Optional[str] = None
    action_label: Optional[str] = None
    action_route: Optional[str] = None
    is_read: bool = False
    created_at: datetime
