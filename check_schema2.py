import asyncio
import asyncpg
async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    rows = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'meal_slots'")
    print([r['column_name'] for r in rows])
asyncio.run(main())
