"""
apply_migration.py
==================
Runs the audit trigger migration SQL directly against the database
using Python + asyncpg, bypassing Prisma's advisory lock entirely.

Use this when `prisma migrate deploy` keeps timing out on Neon.

Run with:
    python apply_migration.py

After it succeeds, tell Prisma the migration is applied:
    prisma migrate resolve --applied "20260319000000_audit_triggers"

Replace the migration folder name with your actual folder name.
"""

import os
import asyncio
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set in environment or .env")

# ── Find the migration SQL file ────────────────────────────────────────────
migrations_dir = Path(__file__).parent / "prisma" / "migrations"
sql_files = sorted(migrations_dir.glob("*_audit_triggers/migration.sql"))

if not sql_files:
    # Fall back: find any migration.sql that contains fn_audit_trigger
    for f in sorted(migrations_dir.glob("*/migration.sql")):
        if "fn_audit_trigger" in f.read_text():
            sql_files = [f]
            break

if not sql_files:
    raise RuntimeError(
        "Could not find the audit triggers migration.sql.\n"
        "Make sure it exists at: prisma/migrations/*_audit_triggers/migration.sql"
    )

SQL_FILE = sql_files[-1]
print(f"Found migration: {SQL_FILE}")


async def run():
    try:
        import asyncpg
    except ImportError:
        raise RuntimeError(
            "asyncpg is not installed.\n"
            "Run:  pip install asyncpg"
        )

    sql = SQL_FILE.read_text(encoding="utf-8")

    # Neon requires SSL. asyncpg accepts the postgres:// URL directly.
    # Strip any Prisma-specific params (connection_limit, pool_timeout etc.)
    # that asyncpg doesn't understand.
    url = DATABASE_URL
    for param in ["connection_limit", "pool_timeout", "connect_timeout",
                  "pgbouncer", "sslaccept"]:
        import re
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    # Clean up trailing ? or &
    url = re.sub(r"[?&]$", "", url)

    print(f"\nConnecting to Neon...")
    conn = await asyncpg.connect(url, ssl=False, timeout=30)
    print("Connected.\n")

    try:
        print("Applying migration SQL...\n")
        # Execute the entire SQL as one block.
        # asyncpg handles multi-statement SQL correctly.
        await conn.execute(sql)
        print("\n✅  Migration applied successfully!")
        print()
        print("Now run:")
        print(f'  prisma migrate resolve --applied "{SQL_FILE.parent.name}"')
        print()
        print("Then verify triggers exist by running:")
        print("  python verify_migration.py")
    except Exception as e:
        print(f"\n❌  Migration failed: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())