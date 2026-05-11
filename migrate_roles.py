import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = os.getenv("DB_PASSWORD", "postgres")
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "canteen_db")

DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

async def migrate_roles():
    conn = await asyncpg.connect(DATABASE_URL)
    print("Connected to database.")
    
    try:
        # 1. Ensure roles exist
        print("Checking roles...")
        roles = await conn.fetch("SELECT id, role_name FROM roles")
        roles_dict = {r["role_name"]: r["id"] for r in roles}
        
        if "canteen_staff" not in roles_dict:
            print("Creating 'canteen_staff' role...")
            staff_role_id = await conn.fetchval(
                "INSERT INTO roles (role_name, description) VALUES ('canteen_staff', 'Canteen staff member') RETURNING id"
            )
            roles_dict["canteen_staff"] = staff_role_id
            
        if "admin" not in roles_dict:
            print("Creating 'admin' role...")
            admin_role_id = await conn.fetchval(
                "INSERT INTO roles (role_name, description) VALUES ('admin', 'System administrator') RETURNING id"
            )
            roles_dict["admin"] = admin_role_id
            
        if "student" not in roles_dict:
            print("Creating 'student' role...")
            student_role_id = await conn.fetchval(
                "INSERT INTO roles (role_name, description) VALUES ('student', 'Student') RETURNING id"
            )
            roles_dict["student"] = student_role_id
            
        admin_id = roles_dict["admin"]
        staff_id = roles_dict["canteen_staff"]
        
        # 2. Find real admins vs staff. 
        # A true admin might be the one NOT in the staff table, or the one with a specific email.
        # Let's see how many users are in the staff table.
        # If a user is in the staff table, they should probably be 'canteen_staff' UNLESS they are designated 'Super Admin'
        print("Updating existing staff accounts to 'canteen_staff' role...")
        
        # Update users who are in the staff table (except maybe 'Super Admin' if that exists)
        # We will change the role_id to staff_id for any user that is linked in the staff table
        # where the user currently has the 'admin' role_id.
        result = await conn.execute("""
            UPDATE users
            SET role_id = $1
            WHERE id IN (
                SELECT user_id FROM staff WHERE designation != 'Super Admin' OR designation IS NULL
            ) AND role_id = $2
        """, staff_id, admin_id)
        
        print(f"Migration completed. {result}")
        
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate_roles())
