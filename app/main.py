import uuid
import traceback
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.database import connect_db, close_db, pool as db_pool
from app.config import settings

from app.routes.auth import router as auth_router, limiter
from app.routes.meals import router as meals_router
from app.routes.bookings import router as bookings_router
from app.routes.feedback import router as feedback_router
from app.routes.tokens import router as tokens_router
from app.routes.notifications import router as notifications_router
from app.routes.leave import router as leave_router
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup event: Connect to database
    await connect_db()
    yield
    # Shutdown event: Close database connection
    await close_db()

app = FastAPI(title="Canteen Backend API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# ── Task 15: Error logging middleware ────────────────────────────────────────
@app.middleware("http")
async def error_logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        print(f"CRITICAL ERROR in {request.url.path}:")
        print(traceback.format_exc())
        
        # Log to error_logs table
        try:
            from app.database import pool
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO error_logs (severity, request_id, endpoint, http_method, status_code, message, stack_trace, exception_type, environment)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        """,
                        "error", request_id, str(request.url.path), request.method, 500,
                        str(exc), traceback.format_exc(), type(exc).__name__,
                        settings.ENVIRONMENT
                    )
        except Exception as log_err:
            logger.error(f"Failed to write error log: {log_err}")
        
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id}
        )

app.include_router(auth_router)
app.include_router(meals_router)
app.include_router(bookings_router)
app.include_router(feedback_router)
app.include_router(tokens_router)
app.include_router(notifications_router)
app.include_router(leave_router)

@app.get("/")
async def root():
    return {"message": "API running"}