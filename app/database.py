import asyncpg
from app.config import settings
import logging

logger = logging.getLogger(__name__)

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
        logger.info("Successfully connected to the database and created pool.")
    except Exception as e:
        logger.error(f"Failed to connect to the database: {e}")
        raise e

async def close_db():
    global pool
    if pool is not None:
        await pool.close()
        logger.info("Database connection pool closed.")
