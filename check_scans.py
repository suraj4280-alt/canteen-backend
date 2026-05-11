import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    rows = await conn.fetch("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'scans'
    """)
    for row in rows:
        print(dict(row))
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
