import asyncio
import asyncpg
from app.services.qr_service import process_scan

async def test_scan():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/canteen_db')
    
    bookings = await conn.fetch("""
        SELECT b.id, b.qr_token, bs.status_name 
        FROM bookings b
        JOIN booking_status bs ON b.status_id = bs.id
        WHERE b.student_id = 3 AND b.date = CURRENT_DATE
    """)
    print("All bookings for student 3 today:")
    for b in bookings:
        print(dict(b))
        
    booking = next((b for b in bookings if b['status_name'] == 'used'), None)
    
    if not booking:
        print("No active booking found for student 3 today.")
        await conn.close()
        return

    print(f"Found active booking: {booking['id']}")
    token_uuid = str(booking['qr_token'])
    print(f"QR Token: {token_uuid}")
    
    # Fix confirmed_at if it's null (due to test scripts)
    await conn.execute("UPDATE bookings SET confirmed_at = created_at WHERE id = $1 AND confirmed_at IS NULL", booking['id'])
    
    # Simulate scanning the QR code as staff ID 1
    print("Scanning QR code...")
    result = await process_scan(conn, token_uuid, 1)
    
    print("\nScan Result:")
    print(result)
    
    if result.get("success"):
        print("\nSUCCESS! The meal has been successfully scanned and marked as USED.")
    else:
        print("\nFAILED:", result.get("detail"))

    await conn.close()

if __name__ == '__main__':
    asyncio.run(test_scan())
