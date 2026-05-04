"""Leave period routes — Task 6"""
from fastapi import APIRouter, Depends, HTTPException
from asyncpg import Connection
from typing import List
from app.dependencies import get_db, get_current_student, require_staff
from app.schemas.leave import LeaveReq, LeaveResp

router = APIRouter(prefix="/api/leave-periods", tags=["leave"])

@router.get("", response_model=List[LeaveResp])
async def get_leave_periods(db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    rows = await db.fetch(
        """
        SELECT id, student_id, start_date, end_date, reason, reason_category,
               is_approved, approved_by, approved_at, created_at
        FROM leave_periods
        WHERE student_id = $1
        ORDER BY start_date DESC
        """,
        student_id
    )
    return [dict(r) for r in rows]

@router.post("", response_model=LeaveResp, status_code=201)
async def create_leave_period(request: LeaveReq, db: Connection = Depends(get_db), student: dict = Depends(get_current_student)):
    student_id = student["student_id"]
    
    if request.end_date < request.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")
    
    # Check for overlapping leave periods
    overlap = await db.fetchval(
        """
        SELECT id FROM leave_periods
        WHERE student_id = $1 AND start_date <= $3 AND end_date >= $2
        """,
        student_id, request.start_date, request.end_date
    )
    if overlap:
        raise HTTPException(status_code=400, detail="Overlapping leave period already exists")
    
    row = await db.fetchrow(
        """
        INSERT INTO leave_periods (student_id, start_date, end_date, reason, reason_category)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, student_id, start_date, end_date, reason, reason_category,
                  is_approved, approved_by, approved_at, created_at
        """,
        student_id, request.start_date, request.end_date,
        request.reason, request.reason_category
    )
    return dict(row)

@router.put("/{leave_id}/approve")
async def approve_leave(leave_id: int, db: Connection = Depends(get_db), staff_user: dict = Depends(require_staff)):
    staff_id = staff_user["staff_id"]
    
    leave = await db.fetchrow("SELECT id, is_approved FROM leave_periods WHERE id = $1", leave_id)
    if not leave:
        raise HTTPException(status_code=404, detail="Leave period not found")
    if leave["is_approved"]:
        raise HTTPException(status_code=400, detail="Leave period already approved")
    
    await db.execute(
        "UPDATE leave_periods SET is_approved = TRUE, approved_by = $1, approved_at = NOW() WHERE id = $2",
        staff_id, leave_id
    )
    return {"message": "Leave period approved"}
