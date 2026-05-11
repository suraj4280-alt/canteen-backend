import asyncio
import asyncpg
from datetime import date, datetime

async def insert_yesterday_bookings():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        # The logged in user is student_id = 3
        student = await conn.fetchrow("SELECT id, user_id, hostel_id FROM students WHERE id = 3")
        print(f"Using student ID: {student['id']}")
        
        # We will mark yesterday's meals as 'used' (meaning you ate them)
        used_status_id = await conn.fetchval("SELECT id FROM booking_status WHERE status_name = 'used'")
        
        yesterday = date(2026, 5, 9)
        
        async with conn.transaction():
            # Get meal slots
            slots = await conn.fetch("SELECT id FROM meal_slots")
            
            for slot in slots:
                slot_id = slot['id']
                
                # Get the menu for this slot and hostel
                menu_id = await conn.fetchval("""
                    SELECT id FROM meal_menus 
                    WHERE meal_slot_id = $1 AND hostel_id = $2 AND date = $3 AND is_active = TRUE
                """, slot_id, student['hostel_id'], yesterday)
                
                if not menu_id:
                    menu_id = await conn.fetchval("""
                        SELECT id FROM meal_menus 
                        WHERE meal_slot_id = $1 AND hostel_id = $2 AND is_recurring = TRUE AND is_active = TRUE
                    """, slot_id, student['hostel_id'])
                
                if not menu_id:
                    continue
                    
                existing = await conn.fetchval("SELECT id FROM bookings WHERE student_id=$1 AND meal_slot_id=$2 AND date=$3", student['id'], slot_id, yesterday)
                
                if existing:
                    print(f"Booking already exists for slot {slot_id} on {yesterday}")
                    await conn.execute("UPDATE bookings SET status_id=$1 WHERE id=$2", used_status_id, existing)
                    booking_id = existing
                else:
                    booking_id = await conn.fetchval("""
                        INSERT INTO bookings (student_id, meal_slot_id, meal_menu_id, date, status_id, created_at, confirmed_at, used_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id
                    """, student['id'], slot_id, menu_id, yesterday, used_status_id, datetime.combine(yesterday, datetime.min.time()), datetime.combine(yesterday, datetime.min.time()), datetime.combine(yesterday, datetime.min.time()))
                    print(f"Inserted history booking {booking_id} for slot {slot_id} on {yesterday}")

            print("Done inserting yesterday's history.")

    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(insert_yesterday_bookings())
