import asyncio
import asyncpg
import sys

async def execute_sql_file():
    sql_path = r"C:\Users\USER\.gemini\antigravity\brain\f917d37c-14fb-42cb-81ce-df0d2c015c14\artifacts\weekly_menu_inserts.sql"
    
    with open(sql_path, 'r') as file:
        sql = file.read()
    
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        # We wrap in a transaction to ensure atomic insert
        async with conn.transaction():
            await conn.execute(sql)
            print("Successfully inserted weekly menu data.")
    except Exception as e:
        print(f"Error executing SQL: {e}")
        sys.exit(1)
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(execute_sql_file())
