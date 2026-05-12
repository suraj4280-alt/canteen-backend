import asyncio
import asyncpg
import ssl
import os
import socket
import subprocess
import re
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
parsed = urlparse(DATABASE_URL)
hostname = parsed.hostname

# DNS Resolution
try:
    socket.getaddrinfo(hostname, 5432)
    host = hostname
except socket.gaierror:
    print(f"[DNS] System DNS failed, trying Google DNS...")
    r = subprocess.run(["nslookup", hostname, "8.8.8.8"], capture_output=True, text=True, timeout=10)
    host = None
    found = False
    for line in r.stdout.splitlines():
        s = line.strip()
        if "Name:" in s or "Addresses:" in s:
            found = True
        if found:
            m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", s)
            if m and m.group(1) != "8.8.8.8":
                host = m.group(1)
                break
    if not host:
        print("FAIL: Could not resolve hostname")
        exit(1)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
endpoint_id = hostname.split(".")[0]

async def run_migration():
    print("Connecting to database...")
    conn = await asyncpg.connect(
        host=host,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip("/"),
        ssl=ctx,
        server_settings={"options": f"endpoint={endpoint_id}"},
    )
    
    with open("migrations/configurable_booking_window.sql", "r") as f:
        sql = f.read()
        
    print("Running migration SQL...")
    await conn.execute(sql)
    print("Migration successful! Added global booking window settings.")
    await conn.close()

asyncio.run(run_migration())
