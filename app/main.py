from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.database import connect_db, close_db

from app.routes.auth import router as auth_router
from app.routes.meals import router as meals_router
from app.routes.bookings import router as bookings_router
from app.routes.tokens import router as tokens_router
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup event: Connect to database
    await connect_db()
    yield
    # Shutdown event: Close database connection
    await close_db()

app = FastAPI(title="Canteen Backend API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(meals_router)
app.include_router(bookings_router)
app.include_router(tokens_router)

@app.get("/")
async def root():
    return {"message": "API running"}