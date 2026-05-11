import asyncio
import asyncpg

async def get_active_user():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        # Find who is actually logged in based on latest valid session
        res = await conn.fetchrow("""
            SELECT s.user_id, st.id as student_id, st.first_name, st.last_name 
            FROM sessions s 
            JOIN students st ON s.user_id = st.user_id 
            WHERE s.revoked = FALSE 
            ORDER BY s.created_at DESC 
            LIMIT 1
        """)
        print(f"Logged in user: {res}")
        
        if res:
            # Check what bookings they have today
            bookings = await conn.fetch("""
                SELECT id, meal_slot_id, date, status_id 
                FROM bookings 
                WHERE student_id = $1 AND date = CURRENT_DATE
            """, res['student_id'])
            print(f"Bookings for student {res['student_id']} today: {bookings}")
            
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(get_active_user())
