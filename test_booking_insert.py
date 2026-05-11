import asyncio
import asyncpg
from datetime import date, datetime

async def insert_test_bookings():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        # The logged in user is student_id = 3
        student = await conn.fetchrow("SELECT id, user_id, hostel_id FROM students WHERE id = 3")
        print(f"Using student ID: {student['id']}")
        
        # Get booked status ID
        booked_status_id = await conn.fetchval("SELECT id FROM booking_status WHERE status_name = 'booked'")
        
        today = date(2026, 5, 10) # Today's date based on system time provided
        
        async with conn.transaction():
            # Get meal slots
            slots = await conn.fetch("SELECT id FROM meal_slots")
            
            for slot in slots:
                slot_id = slot['id']
                
                # Get the menu for this slot and hostel
                menu_id = await conn.fetchval("""
                    SELECT id FROM meal_menus 
                    WHERE meal_slot_id = $1 AND hostel_id = $2 AND date = $3 AND is_active = TRUE
                """, slot_id, student['hostel_id'], today)
                
                if not menu_id:
                    # Fallback to recurring
                    menu_id = await conn.fetchval("""
                        SELECT id FROM meal_menus 
                        WHERE meal_slot_id = $1 AND hostel_id = $2 AND is_recurring = TRUE AND is_active = TRUE
                    """, slot_id, student['hostel_id'])
                
                if not menu_id:
                    print(f"No menu found for slot {slot_id}")
                    continue
                    
                # Check if booking exists
                existing = await conn.fetchval("SELECT id FROM bookings WHERE student_id=$1 AND meal_slot_id=$2 AND date=$3", student['id'], slot_id, today)
                
                if existing:
                    print(f"Booking already exists for slot {slot_id}")
                    await conn.execute("UPDATE bookings SET status_id=$1 WHERE id=$2", booked_status_id, existing)
                    booking_id = existing
                else:
                    booking_id = await conn.fetchval("""
                        INSERT INTO bookings (student_id, meal_slot_id, meal_menu_id, date, status_id, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                    """, student['id'], slot_id, menu_id, today, booked_status_id, datetime.combine(today, datetime.min.time()))
                    print(f"Inserted booking {booking_id} for slot {slot_id}")
                
                # Insert a dummy item for the booking if not exists
                item_exists = await conn.fetchval("SELECT id FROM booking_items WHERE booking_id=$1", booking_id)
                if not item_exists:
                    menu_item_id = await conn.fetchval("SELECT menu_item_id FROM meal_menu_items WHERE meal_menu_id=$1 LIMIT 1", menu_id)
                    if menu_item_id:
                        await conn.execute("""
                            INSERT INTO booking_items (booking_id, menu_item_id, quantity)
                            VALUES ($1, $2, $3)
                        """, booking_id, menu_item_id, 1)

            print("Done inserting bookings for today.")

    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(insert_test_bookings())
