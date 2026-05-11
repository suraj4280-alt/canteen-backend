"""Quick smoke test: verify Neon PostgreSQL connection is working."""
import asyncio
import asyncpg
import ssl
import os
import subprocess
import socket
import re
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
parsed = urlparse(DATABASE_URL)
hostname = parsed.hostname

# --- Resolve hostname (Google DNS fallback) ---
try:
    socket.getaddrinfo(hostname, 5432)
    host = hostname
    print(f"[DNS] System DNS resolved {hostname}")
except socket.gaierror:
    print(f"[DNS] System DNS failed, trying Google DNS (8.8.8.8)...")
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
    print(f"[DNS] Resolved -> {host}")

# --- SSL context ---
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

endpoint_id = hostname.split(".")[0]


async def test():
    print("\n--- Connecting to Neon ---")
    conn = await asyncpg.connect(
        host=host,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip("/"),
        ssl=ctx,
        server_settings={"options": f"endpoint={endpoint_id}"},
    )

    # 1. PostgreSQL version
    version = await conn.fetchval("SELECT version()")
    print(f"PostgreSQL: {version}")

    # 2. List tables
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    print(f"\nTables ({len(tables)}):")
    for t in tables:
        print(f"  - {t['tablename']}")

    # 3. User count
    count = await conn.fetchval("SELECT count(*) FROM users")
    print(f"\nTotal users: {count}")

    # 4. Current time from server
    now = await conn.fetchval("SELECT now()")
    print(f"Server time: {now}")

    await conn.close()
    print("\n✅ ALL CHECKS PASSED — Neon is working!")


asyncio.run(test())
