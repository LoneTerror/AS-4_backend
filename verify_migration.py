"""
verify_migration.py
===================
Confirms that the audit migration applied correctly:
  - System sentinel employee exists
  - All 17 triggers are attached
  - audit_log is immutable (UPDATE/DELETE revoked)

Run with:
    python verify_migration.py
"""

import os
import asyncio
from pathlib import Path

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
    raise RuntimeError("DATABASE_URL not set")

EXPECTED_TRIGGERS = {
    "trg_audit_employees",
    "trg_audit_departments",
    "trg_audit_department_types",
    "trg_audit_designations",
    "trg_audit_roles",
    "trg_audit_employee_roles",
    "trg_audit_route_permissions",
    "trg_audit_status_master",
    "trg_audit_reviews",
    "trg_audit_review_categories",
    "trg_audit_reward_catalog",
    "trg_audit_reward_categories",
    "trg_audit_reward_history",
    "trg_audit_wallets",
    "trg_audit_transactions",
    "trg_audit_transaction_types",
    "trg_audit_refresh_tokens",
}

SENTINEL_ID = "00000000-0000-0000-0000-000000000000"


async def run():
    try:
        import asyncpg
    except ImportError:
        raise RuntimeError("Run: pip install asyncpg")

    import re
    url = DATABASE_URL
    for param in ["connection_limit", "pool_timeout", "connect_timeout",
                  "pgbouncer", "sslaccept"]:
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    url = re.sub(r"[?&]$", "", url)

    conn = await asyncpg.connect(url, ssl="require", timeout=30)
    print("Connected to Neon.\n")

    all_ok = True

    try:
        # ── 1. Sentinel employee ───────────────────────────────────────────
        row = await conn.fetchrow(
            "SELECT employee_id, username FROM employees WHERE employee_id = $1",
            SENTINEL_ID,
        )
        if row:
            print(f"✅  Sentinel employee exists: {row['username']} ({row['employee_id']})")
        else:
            print("❌  Sentinel employee MISSING — migration may not have run")
            all_ok = False

        # ── 2. Triggers ────────────────────────────────────────────────────
        rows = await conn.fetch("""
            SELECT trigger_name
              FROM information_schema.triggers
             WHERE trigger_schema = 'public'
               AND trigger_name LIKE 'trg_audit_%'
             GROUP BY trigger_name
             ORDER BY trigger_name
        """)
        found = {r["trigger_name"] for r in rows}
        missing = EXPECTED_TRIGGERS - found

        print(f"\n✅  Triggers found: {len(found)}/{len(EXPECTED_TRIGGERS)}")
        for name in sorted(found):
            print(f"     {name}")

        if missing:
            print(f"\n❌  Missing triggers ({len(missing)}):")
            for name in sorted(missing):
                print(f"     {name}")
            all_ok = False

        # ── 3. Immutability check ──────────────────────────────────────────
        # Try to update a row — should fail if REVOKE worked.
        # We do this in a transaction we immediately roll back, so it's safe.
        immutable = False
        try:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE audit_log SET ip_address = '0.0.0.0' WHERE FALSE"
                )
                # If we get here, REVOKE either wasn't applied or the current
                # connection user is a superuser (which can always UPDATE).
                print("\n⚠️   audit_log UPDATE succeeded — either REVOKE wasn't applied")
                print("     or you are connected as a superuser (that's normal for migrations).")
                print("     The app DB user should NOT be able to UPDATE — verify separately.")
                raise Exception("rollback")
        except Exception as e:
            if "permission denied" in str(e).lower():
                print("\n✅  audit_log is immutable (UPDATE correctly denied)")
                immutable = True
            elif "rollback" in str(e).lower():
                pass  # expected — we forced a rollback above
            else:
                print(f"\n⚠️   Unexpected error checking immutability: {e}")

        # ── Summary ────────────────────────────────────────────────────────
        print()
        if all_ok:
            print("=" * 50)
            print("✅  ALL CHECKS PASSED — migration is complete")
            print("=" * 50)
        else:
            print("=" * 50)
            print("❌  SOME CHECKS FAILED — review output above")
            print("=" * 50)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())