import asyncpg
from app.config import settings

pool = None

async def connect_db():
    global pool
    try:
        pool = await asyncpg.create_pool(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            min_size=1,
            max_size=10
        )
        print("Successfully connected to the database and created pool.")
    except Exception as e:
        print(f"Failed to connect to the database: {e}")
        raise e

async def close_db():
    global pool
    if pool is not None:
        await pool.close()
        print("Database connection pool closed.")
