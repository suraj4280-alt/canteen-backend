import asyncpg
import ssl
import os
import re
import socket
import subprocess
import logging
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
logger = logging.getLogger(__name__)

pool = None

# Create SSL context for Neon (cloud PostgreSQL) — asyncpg does NOT
# read sslmode=require from the DSN, so we must pass it explicitly.
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# IPv4 address pattern
_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _resolve_neon_host(hostname: str) -> str:
    """Resolve Neon hostname, falling back to Google DNS (8.8.8.8).

    Some local DNS servers (corporate/ISP) refuse queries for neon.tech
    domains.  This helper falls back to Google public DNS when the
    system resolver fails.
    """
    # 1. Try system DNS first
    try:
        socket.getaddrinfo(hostname, 5432)
        logger.info("System DNS resolved %s successfully", hostname)
        return hostname  # system DNS works, use hostname as-is
    except socket.gaierror:
        logger.warning(
            "System DNS failed for %s, falling back to Google DNS (8.8.8.8)",
            hostname,
        )

    # 2. Fallback: query Google DNS via nslookup and extract an IPv4 address
    try:
        result = subprocess.run(
            ["nslookup", hostname, "8.8.8.8"],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout

        # Find the "Non-authoritative answer" or "Name:" section
        # then grab any IPv4 address that is NOT 8.8.8.8
        found_answer = False
        for line in output.splitlines():
            stripped = line.strip()
            if "Name:" in stripped or "Addresses:" in stripped:
                found_answer = True
            if found_answer:
                match = _IPV4_RE.search(stripped)
                if match:
                    ip = match.group(1)
                    if ip != "8.8.8.8":
                        logger.info("Resolved %s -> %s via Google DNS", hostname, ip)
                        return ip
    except Exception as e:
        logger.error("Google DNS fallback via nslookup failed: %s", e)

    raise RuntimeError(
        f"Cannot resolve {hostname}. "
        "Fix your DNS settings or add the host to your system hosts file."
    )


async def connect_db():
    global pool
    try:
        logger.info("Connecting to Neon PostgreSQL...")

        # Parse DSN to resolve hostname (works around broken local DNS)
        parsed = urlparse(DATABASE_URL)
        resolved_host = _resolve_neon_host(parsed.hostname)

        # When connecting via IP (DNS fallback), Neon's proxy can't
        # identify the endpoint from SNI.  Pass the endpoint ID explicitly.
        endpoint_id = parsed.hostname.split(".")[0]  # e.g. "ep-bitter-bread-aok9r6jb"

        pool = await asyncpg.create_pool(
            host=resolved_host,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
            ssl=ssl_ctx,
            min_size=1,
            max_size=10,
            timeout=30,
            server_settings={
                "options": f"endpoint={endpoint_id} -c search_path=public",
            },
        )
        print("Database connected successfully", flush=True)
        logger.info("Successfully connected to Neon and created pool.")
    except Exception as e:
        logger.error(f"Failed to connect to the database: {e}")
        raise e


async def close_db():
    global pool
    if pool is not None:
        await pool.close()
        logger.info("Database connection pool closed.")
