import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    rows = await conn.fetch("""
        SELECT name, start_time, end_time, booking_open_time, booking_open_day_offset, booking_cutoff_time
        FROM meal_slots WHERE is_active = TRUE ORDER BY display_order
    """)
    print("Meal Slots in DB:")
    for r in rows:
        d = dict(r)
        offset = "prev day" if d['booking_open_day_offset'] == -1 else "same day"
        print(f"  {d['name']:12s} | Meal: {d['start_time']}-{d['end_time']} | "
              f"Book: {d['booking_open_time']}-{d['booking_cutoff_time']} ({offset})")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
