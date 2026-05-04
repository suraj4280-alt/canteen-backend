import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        rows = await conn.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'scans'")
        print("Scans table columns:")
        for r in rows:
            print(f"- {r['column_name']} ({r['data_type']})")
        
        scans_exist = await conn.fetchval("SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = 'scans')")
        print(f"\nScans table exists: {scans_exist}")
    finally:
        await conn.close()

asyncio.run(main())
