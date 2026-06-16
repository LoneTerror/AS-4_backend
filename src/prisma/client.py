import os
import asyncio
from prisma import Prisma

_BASE_URL = os.environ.get("DATABASE_URL")
if not _BASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "  Local dev: create a .env file in the project root.\n"
        "  Production: set it in your Docker run command or secrets manager."
    )

_SEP    = "&" if "?" in _BASE_URL else "?"
_DB_URL = f"{_BASE_URL}{_SEP}connection_limit=3&pool_timeout=15&connect_timeout=10"

db = Prisma(datasource={"url": _DB_URL})


async def connect_with_retry(retries: int = 5, delay: float = 3.0) -> None:
    """
    Connect to the database with retry logic.
    In prod all services start simultaneously — this gives the DB time
    to accept connections instead of failing hard on the first attempt.
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


async def set_audit_context(
    user_id:    str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    Set Postgres session-local variables that the audit trigger reads.

    Must be called on the SAME connection and BEFORE the mutating query.
    Prisma's connection pool means you cannot guarantee the same physical
    connection across two separate execute_raw() calls — so we set all
    three variables in a single round-trip.

    The 'true' flag in set_config makes the setting LOCAL to the current
    transaction, which is what we want: it resets after the transaction
    commits or rolls back, so a pooled connection can never leak one
    request's user_id into the next request.

    Called automatically by the `audit_context` async context manager
    in src/common/audit.py — you should use that instead of calling
    this directly.
    """
    await db.execute_raw(
        """
        SELECT
          set_config('app.current_user_id', $1, true),
          set_config('app.client_ip',        $2, true),
          set_config('app.user_agent',       $3, true)
        """,
        user_id,
        ip_address  or "",
        user_agent  or "",
    )