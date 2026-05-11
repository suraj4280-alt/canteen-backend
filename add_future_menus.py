import asyncio
import asyncpg
from datetime import timedelta

async def copy_menus():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    try:
        async with conn.transaction():
            # Get existing menus
            menus = await conn.fetch("SELECT * FROM meal_menus WHERE date >= '2026-05-04' AND date <= '2026-05-10'")
            for menu in menus:
                new_date = menu['date'] + timedelta(days=7)
                
                # Check if already exists
                exists = await conn.fetchval("SELECT id FROM meal_menus WHERE hostel_id=$1 AND meal_slot_id=$2 AND date=$3", 
                    menu['hostel_id'], menu['meal_slot_id'], new_date)
                
                if not exists:
                    new_menu_id = await conn.fetchval("""
                        INSERT INTO meal_menus (hostel_id, meal_slot_id, date, is_active)
                        VALUES ($1, $2, $3, $4) RETURNING id
                    """, menu['hostel_id'], menu['meal_slot_id'], new_date, True)
                    
                    # Copy items
                    items = await conn.fetch("SELECT * FROM meal_menu_items WHERE meal_menu_id=$1", menu['id'])
                    for item in items:
                        await conn.execute("""
                            INSERT INTO meal_menu_items (meal_menu_id, menu_item_id, quantity, quantity_value, unit, is_default, is_optional, max_selectable, sort_order, exclusive_group)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        """, new_menu_id, item['menu_item_id'], item['quantity'], item['quantity_value'], item['unit'], item['is_default'], item['is_optional'], item['max_selectable'], item['sort_order'], item['exclusive_group'])
                    print(f"Copied menu from {menu['date']} to {new_date}")
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(copy_menus())
