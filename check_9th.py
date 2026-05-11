import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        res = await conn.fetch("SELECT b.id, ms.name as meal_name, bs.status_name FROM bookings b JOIN meal_slots ms ON b.meal_slot_id = ms.id JOIN booking_status bs ON b.status_id = bs.id WHERE b.date = '2026-05-09'")
        for row in res:
            print(f"Booking ID: {row['id']} - Meal: {row['meal_name']} - Status: {row['status_name']}")
        if not res:
            print("No bookings found for 2026-05-09")
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(check())
