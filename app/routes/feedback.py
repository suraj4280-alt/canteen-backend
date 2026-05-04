from fastapi import APIRouter, Depends, HTTPException
from asyncpg import Connection
from typing import List
from app.dependencies import get_db, get_current_student
from app.schemas.feedback import FeedbackReq, FeedbackResp, FeedbackTagResp

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

@router.get("/tags", response_model=List[FeedbackTagResp])
async def get_feedback_tags(db: Connection = Depends(get_db)):
    rows = await db.fetch("SELECT id, tag_name, display_label, color_code, icon_name FROM feedback_tags WHERE is_active = TRUE ORDER BY sort_order")
    return [dict(r) for r in rows]

@router.post("", response_model=FeedbackResp, status_code=201)
async def create_feedback(request: FeedbackReq, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    # Verify booking belongs to this student
    booking = await db.fetchrow(
        "SELECT id, student_id FROM bookings WHERE id = $1", 
        request.booking_id
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["student_id"] != student_id:
        raise HTTPException(status_code=403, detail="Not authorized to review this booking")
    
    # Check for duplicate feedback
    existing = await db.fetchval(
        "SELECT id FROM feedback WHERE booking_id = $1 AND student_id = $2",
        request.booking_id, student_id
    )
    if existing:
        raise HTTPException(status_code=400, detail="Feedback already submitted for this booking")
    
    async with db.transaction():
        row = await db.fetchrow(
            """
            INSERT INTO feedback (student_id, booking_id, food_rating, service_rating, cleanliness_rating, comment)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, booking_id, food_rating, service_rating, cleanliness_rating, comment, created_at
            """,
            student_id, request.booking_id,
            request.food_rating, request.service_rating, request.cleanliness_rating,
            request.comment
        )
        
        # Task 16: Insert feedback tags
        if request.tag_ids:
            for tag_id in request.tag_ids:
                await db.execute(
                    "INSERT INTO feedback_tag_links (feedback_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    row["id"], tag_id
                )
    
    return dict(row)

@router.get("", response_model=List[FeedbackResp])
async def get_feedback(db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    rows = await db.fetch(
        """
        SELECT id, booking_id, food_rating, service_rating, cleanliness_rating, comment, created_at
        FROM feedback 
        WHERE student_id = $1 
        ORDER BY created_at DESC
        """,
        student_id
    )
    return [dict(r) for r in rows]
