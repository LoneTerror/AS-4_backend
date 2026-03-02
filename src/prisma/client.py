import os
import asyncio
from prisma import Prisma
import asyncio
import logging

_BASE_URL = os.environ.get("DATABASE_URL")
if not _BASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "  Local dev: create a .env file in the project root.\n"
        "  Production: set it in your Docker run command or secrets manager."
    )

# Avoid double-appending params if DATABASE_URL already has a query string
_SEP = "&" if "?" in _BASE_URL else "?"
_DB_URL = f"{_BASE_URL}{_SEP}connection_limit=3&pool_timeout=15&connect_timeout=10"

db = Prisma(datasource={"url": _DB_URL})


async def connect_with_retry(retries: int = 5, delay: float = 3.0) -> None:
    """
    Connect to the database with retry logic.

    In prod all 7 services start simultaneously and compete for the DB.
    This gives the DB time to accept connections instead of failing hard
    on the first attempt.

    Args:
        retries: Number of attempts before giving up.
        delay:   Seconds to wait between attempts.
    """
    for attempt in range(1, retries + 1):
        try:
            await db.connect()
            return
        except Exception as e:
            if attempt == retries:
                raise RuntimeError(
                    f"Database connection failed after {retries} attempts: {e}"
                ) from e
            print(f"DB connection attempt {attempt}/{retries} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
