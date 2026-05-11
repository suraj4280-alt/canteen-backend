import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    rows = await conn.fetch("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conrelid = 'meal_slots'::regclass
    """)
    for r in rows:
        print(f"{r['conname']}: {r['definition']}")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
