"""Migration: Add booking_open_time and booking_open_day_offset to meal_slots, update slot times."""
import asyncio
import asyncpg

async def migrate():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    
    # 1. Add new columns if they don't exist
    await conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'meal_slots' AND column_name = 'booking_open_time') THEN
                ALTER TABLE meal_slots ADD COLUMN booking_open_time TIME;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name = 'meal_slots' AND column_name = 'booking_open_day_offset') THEN
                ALTER TABLE meal_slots ADD COLUMN booking_open_day_offset INTEGER DEFAULT 0;
            END IF;
        END $$;
    """)
    print("[OK] Added columns: booking_open_time, booking_open_day_offset")
    
    # Drop old constraints that assumed same-day cutoff < end_time
    # These don't make sense for cross-day booking windows
    await conn.execute("""
        ALTER TABLE meal_slots DROP CONSTRAINT IF EXISTS chk_cutoff;
        ALTER TABLE meal_slots DROP CONSTRAINT IF EXISTS chk_cancel_cutoff;
    """)
    print("[OK] Dropped old chk_cutoff and chk_cancel_cutoff constraints")
    
    # 2. Update each slot with correct times, booking window, and cutoff
    #    Breakfast: meal 07:00-09:00, books prev day 18:00-21:00
    await conn.execute("""
        UPDATE meal_slots SET 
            start_time = '07:00:00',
            end_time = '09:00:00',
            booking_open_time = '18:00:00',
            booking_open_day_offset = -1,
            booking_cutoff_time = '21:00:00'
        WHERE LOWER(name) = 'breakfast'
    """)
    print("[OK] Updated Breakfast: 7:00-9:00 AM, booking window prev day 6:00-9:00 PM")
    
    #    Lunch: meal 12:00-14:00, books prev day 18:00-21:00
    await conn.execute("""
        UPDATE meal_slots SET 
            start_time = '12:00:00',
            end_time = '14:00:00',
            booking_open_time = '18:00:00',
            booking_open_day_offset = -1,
            booking_cutoff_time = '21:00:00'
        WHERE LOWER(name) = 'lunch'
    """)
    print("[OK] Updated Lunch: 12:00-2:00 PM, booking window prev day 6:00-9:00 PM")
    
    #    Snacks: meal 17:00-18:00, books same day 09:00-12:00
    await conn.execute("""
        UPDATE meal_slots SET 
            start_time = '17:00:00',
            end_time = '18:00:00',
            booking_open_time = '09:00:00',
            booking_open_day_offset = 0,
            booking_cutoff_time = '12:00:00'
        WHERE LOWER(name) = 'snacks'
    """)
    print("[OK] Updated Snacks: 5:00-6:00 PM, booking window same day 9:00 AM-12:00 PM")
    
    #    Dinner: meal 19:00-21:00, books same day 09:00-12:00
    await conn.execute("""
        UPDATE meal_slots SET 
            start_time = '19:00:00',
            end_time = '21:00:00',
            booking_open_time = '09:00:00',
            booking_open_day_offset = 0,
            booking_cutoff_time = '12:00:00'
        WHERE LOWER(name) = 'dinner'
    """)
    print("[OK] Updated Dinner: 7:00-9:00 PM, booking window same day 9:00 AM-12:00 PM")
    
    # 3. Verify
    rows = await conn.fetch("""
        SELECT name, start_time, end_time, booking_open_time, booking_open_day_offset, booking_cutoff_time 
        FROM meal_slots ORDER BY display_order
    """)
    print("\n-- Final State --")
    for r in rows:
        d = dict(r)
        offset_label = "prev day" if d['booking_open_day_offset'] == -1 else "same day"
        print(f"  {d['name']:12s} | Meal: {d['start_time']}-{d['end_time']} | "
              f"Book: {d['booking_open_time']}-{d['booking_cutoff_time']} ({offset_label})")
    
    await conn.close()
    print("\n[OK] Migration complete!")

if __name__ == '__main__':
    asyncio.run(migrate())
