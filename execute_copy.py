import asyncio
import asyncpg
import sys

async def execute_sql_file():
    sql = """
WITH source_hostel AS (
    SELECT hostel_id FROM meal_menus LIMIT 1
),
source_data AS (
    SELECT id AS old_menu_id,
           meal_slot_id,
           date,
           is_active
    FROM meal_menus
    WHERE hostel_id = (SELECT hostel_id FROM source_hostel)
),
new_menus AS (
    SELECT nextval('meal_menus_id_seq') AS new_menu_id,
           sd.old_menu_id,
           h.id AS target_hostel_id,
           sd.meal_slot_id,
           sd.date,
           sd.is_active
    FROM source_data sd
    CROSS JOIN hostels h
    WHERE h.id != (SELECT hostel_id FROM source_hostel)
      AND NOT EXISTS (
          SELECT 1 FROM meal_menus mm 
          WHERE mm.hostel_id = h.id 
            AND mm.date = sd.date 
            AND mm.meal_slot_id = sd.meal_slot_id
      )
),
inserted_menus AS (
    INSERT INTO meal_menus (id, meal_slot_id, hostel_id, date, is_active)
    SELECT new_menu_id, meal_slot_id, target_hostel_id, date, is_active
    FROM new_menus
    RETURNING id
)
INSERT INTO meal_menu_items (meal_menu_id, menu_item_id)
SELECT nm.new_menu_id, mmi.menu_item_id
FROM new_menus nm
JOIN meal_menu_items mmi ON mmi.meal_menu_id = nm.old_menu_id;
    """
    
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        # We wrap in a transaction to ensure atomic insert
        async with conn.transaction():
            await conn.execute(sql)
            print("Successfully executed.")
    except Exception as e:
        print(f"Error executing SQL: {e}")
        sys.exit(1)
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(execute_sql_file())
