import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    rows = await conn.fetch('''
        SELECT u.email, u.role, s.first_name, s.last_name, s.designation 
        FROM staff s 
        JOIN users u ON s.user_id = u.id 
        LIMIT 5
    ''')
    print('--- Staff Users with Email ---')
    for r in rows:
        print(dict(r))
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
