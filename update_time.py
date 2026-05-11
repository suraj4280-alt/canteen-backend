import asyncio
import asyncpg

async def update_time():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        await conn.execute("UPDATE meal_slots SET start_time = '18:00:00' WHERE id = 4")
        print("Dinner start time temporarily changed to 18:00 to allow testing right now.")
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(update_time())
