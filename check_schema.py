import asyncio
import asyncpg
async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    rows = await conn.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'menu_items'")
    for r in rows:
        print(dict(r))
asyncio.run(main())
