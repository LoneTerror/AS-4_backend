"""
Database cleanup script for Employee Rewards System.
Truncates all tables in the correct order (CASCADE) and verifies the DB is empty.

Run with:
    python unseed.py

What's cleared (all 21 tables):
    audit_log, review_category_tags, reviews, transactions, reward_history,
    refresh_tokens, employee_roles, wallets, notifications, employees,
    reward_catalog, reward_categories, transaction_types, review_categories,
    seasonal_multipliers, designations, departments, department_types,
    route_permissions, roles, status_master
"""
import os
from pathlib import Path

# ── Load .env before anything else ────────────────────────────────────────────
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)

import asyncio

from src.prisma.client import db


# ─────────────────────────────────────────────────────────────────────────────
# DELETION ORDER
# Leaf tables first → parent tables last to respect FK constraints
# (used as fallback if CASCADE TRUNCATE fails)
# ─────────────────────────────────────────────────────────────────────────────
DELETION_ORDER = [
    ("audit_log",             lambda: db.audit_log),
    ("review_category_tags",  lambda: db.review_category_tags),
    ("reviews",               lambda: db.reviews),
    ("transactions",          lambda: db.transactions),
    ("reward_history",        lambda: db.reward_history),
    ("refresh_tokens",        lambda: db.refresh_tokens),
    ("employee_roles",        lambda: db.employee_roles),
    ("wallets",               lambda: db.wallets),
    ("notifications",         lambda: db.notifications),
    ("employees",             lambda: db.employees),
    ("reward_catalog",        lambda: db.reward_catalog),
    ("reward_categories",     lambda: db.reward_categories),
    ("transaction_types",     lambda: db.transaction_types),
    ("review_categories",     lambda: db.review_categories),
    ("seasonal_multipliers",  lambda: db.seasonal_multipliers),
    ("designations",          lambda: db.designations),
    ("departments",           lambda: db.departments),
    ("department_types",      lambda: db.department_types),
    ("route_permissions",     lambda: db.route_permissions),
    ("roles",                 lambda: db.roles),
    ("status_master",         lambda: db.status_master),
]


# ─────────────────────────────────────────────────────────────────────────────
# TRUNCATE (primary strategy)
# ─────────────────────────────────────────────────────────────────────────────
async def truncate_all() -> bool:
    """
    Attempt a single CASCADE TRUNCATE across all 21 tables.
    Returns True if successful, False if it should fall back to delete_many().
    """
    print("⚡ Attempting CASCADE TRUNCATE on all tables...")
    try:
        await db.execute_raw("""
            TRUNCATE TABLE
                audit_log,
                review_category_tags,
                reviews,
                transactions,
                reward_history,
                refresh_tokens,
                employee_roles,
                wallets,
                notifications,
                employees,
                reward_catalog,
                reward_categories,
                transaction_types,
                review_categories,
                seasonal_multipliers,
                designations,
                departments,
                department_types,
                route_permissions,
                roles,
                status_master
            CASCADE
        """)
        print("   ✓ CASCADE TRUNCATE successful — all tables emptied\n")
        return True
    except Exception as e:
        print(f"   ⚠ CASCADE TRUNCATE failed: {e}")
        print("   → Falling back to sequential delete_many()...\n")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DELETE MANY (fallback strategy)
# ─────────────────────────────────────────────────────────────────────────────
async def delete_all_sequential():
    """
    Delete rows table-by-table in FK-safe order.
    Used when TRUNCATE CASCADE is unavailable (e.g. permission restrictions).
    """
    print("🗑️  Sequential delete_many() — leaf → parent order:")
    total_deleted = 0
    errors = []

    for name, table_fn in DELETION_ORDER:
        try:
            count = await table_fn().delete_many()
            total_deleted += count
            status = f"{count} rows" if count else "already empty"
            print(f"   ✓ {name:<25s}  {status}")
        except Exception as ex:
            errors.append((name, str(ex)))
            print(f"   ✗ {name:<25s}  ERROR: {ex}")

    print()
    print(f"   📊 Total rows deleted: {total_deleted}")
    if errors:
        print(f"   ⚠️  {len(errors)} table(s) had errors:")
        for name, err in errors:
            print(f"      • {name}: {err}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY
# ─────────────────────────────────────────────────────────────────────────────
async def verify_empty():
    """Check every table and report any remaining rows."""
    print("🔍 Verifying all tables are empty...")

    checks = [
        ("status_master",         db.status_master.count),
        ("transaction_types",     db.transaction_types.count),
        ("roles",                 db.roles.count),
        ("department_types",      db.department_types.count),
        ("departments",           db.departments.count),
        ("designations",          db.designations.count),
        ("review_categories",     db.review_categories.count),
        ("seasonal_multipliers",  db.seasonal_multipliers.count),
        ("employees",             db.employees.count),
        ("wallets",               db.wallets.count),
        ("employee_roles",        db.employee_roles.count),
        ("reward_categories",     db.reward_categories.count),
        ("reward_catalog",        db.reward_catalog.count),
        ("reviews",               db.reviews.count),
        ("review_category_tags",  db.review_category_tags.count),
        ("transactions",          db.transactions.count),
        ("reward_history",        db.reward_history.count),
        ("refresh_tokens",        db.refresh_tokens.count),
        ("notifications",         db.notifications.count),
        ("route_permissions",     db.route_permissions.count),
        ("audit_log",             db.audit_log.count),
    ]

    all_clear = True
    for name, count_fn in checks:
        try:
            count = await count_fn()
            if count == 0:
                print(f"   ✅ {name:<25s}  empty")
            else:
                print(f"   ❌ {name:<25s}  {count} rows remaining!")
                all_clear = False
        except Exception as ex:
            print(f"   ⚠️  {name:<25s}  could not verify: {ex}")
            all_clear = False

    print()
    return all_clear


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    await db.connect()
    try:
        print("=" * 65)
        print("🧹  EMPLOYEE REWARDS SYSTEM — DATABASE CLEANUP")
        print("=" * 65)
        print()

        # ── Step 1: Try fast CASCADE TRUNCATE ─────────────────────────────────
        success = await truncate_all()

        # ── Step 2: Fall back to sequential deletes if TRUNCATE failed ─────────
        if not success:
            await delete_all_sequential()

        # ── Step 3: Verify everything is gone ──────────────────────────────────
        all_clear = await verify_empty()

        print("=" * 65)
        if all_clear:
            print("🎉  CLEANUP COMPLETE — database is empty!")
        else:
            print("⚠️   CLEANUP FINISHED WITH WARNINGS — some rows may remain.")
            print("    Check the verification output above.")
        print("=" * 65)
        print()
        print("ℹ️   To re-populate the database run:")
        print("      python .\\seed.py")
        print("      python .\\seed_routes.py")
        print()

    except Exception as e:
        print(f"\n❌ Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())