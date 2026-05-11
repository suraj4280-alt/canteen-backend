import asyncio
import asyncpg

async def setup():
    conn = await asyncpg.connect(user='postgres', password='postgres', host='127.0.0.1', port=5432, database='postgres')
    try:
        await conn.execute("CREATE USER neondb_owner WITH PASSWORD 'npg_RGUNozO8Ir7b';")
    except Exception as e:
        print(e)
    try:
        await conn.execute("CREATE DATABASE neondb OWNER neondb_owner;")
    except Exception as e:
        print(e)
    await conn.close()

asyncio.run(setup())
