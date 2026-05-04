import asyncio
import asyncpg
from app.config import settings
DATABASE_URL = f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"

async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT * FROM booking_status WHERE status_name = 'missed'")
    if not row:
        await conn.execute("INSERT INTO booking_status (status_name, is_terminal, display_label, color_code, icon_name, counts_as_meal, counts_as_skip, sort_order) VALUES ('missed', TRUE, 'Missed', '#FF9800', 'warning', FALSE, TRUE, 8)")
        print('Inserted missed status')
    else:
        print('Missed status already exists')
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
