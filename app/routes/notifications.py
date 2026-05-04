"""Notification routes — Task 5"""
from fastapi import APIRouter, Depends, HTTPException
from asyncpg import Connection
from typing import List
from app.dependencies import get_db, get_current_user
from app.schemas.notifications import NotificationResp

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

@router.get("", response_model=List[NotificationResp])
async def get_notifications(db: Connection = Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    
    rows = await db.fetch(
        """
        SELECT n.id, n.title, n.message, n.type, n.priority,
               n.action_label, n.action_route, n.created_at,
               COALESCE(nr.is_read, FALSE) as is_read
        FROM notifications n
        LEFT JOIN notification_recipients nr ON nr.notification_id = n.id AND nr.user_id = $1
        WHERE n.user_id = $1
           OR n.role_id = (SELECT role_id FROM users WHERE id = $1)
           OR n.hostel_id IN (SELECT hostel_id FROM students WHERE user_id = $1)
        ORDER BY n.created_at DESC
        LIMIT 50
        """,
        user_id
    )
    return [dict(r) for r in rows]

@router.put("/{notification_id}/read")
async def mark_notification_read(notification_id: int, db: Connection = Depends(get_db), current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    
    # Verify notification exists
    exists = await db.fetchval("SELECT id FROM notifications WHERE id = $1", notification_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    await db.execute(
        """
        INSERT INTO notification_recipients (notification_id, user_id, is_read, read_at)
        VALUES ($1, $2, TRUE, NOW())
        ON CONFLICT (notification_id, user_id) DO UPDATE SET is_read = TRUE, read_at = NOW()
        """,
        notification_id, user_id
    )
    return {"message": "Notification marked as read"}
