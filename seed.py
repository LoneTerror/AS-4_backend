"""
Complete database seeding script for Employee Rewards System.
Self-contained — seeds everything from scratch in the correct order.

Run with:
    python seed.py
"""
import asyncio
from datetime import datetime, timezone
from src.prisma.client import db
from src.core.security import hash_password


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TEST_PASSWORD = "Password123!"

ADMIN_ID         = "110e8400-e29b-41d4-a716-446655440000"
JANE_ID          = "880e8400-e29b-41d4-a716-446655440000"
JOHN_ID          = "550e8400-e29b-41d4-a716-446655440000"

ACTIVE_STATUS_ID = "990e8400-e29b-41d4-a716-446655440000"

ENG_DEPT_ID      = "770e8400-e29b-41d4-a716-446655440000"
HR_DEPT_ID       = "330e8400-e29b-41d4-a716-446655440000"
TECH_TYPE_ID     = "aa0e8400-e29b-41d4-a716-446655440001"
MGMT_TYPE_ID     = "aa0e8400-e29b-41d4-a716-446655440002"

SR_DEV_DESIG_ID  = "660e8400-e29b-41d4-a716-446655440000"
MGR_DESIG_ID     = "660e8400-e29b-41d4-a716-446655440001"
ADMIN_DESIG_ID   = "660e8400-e29b-41d4-a716-446655440002"

# Transaction type IDs
CREDIT_TYPE_ID           = "bb0e8400-e29b-41d4-a716-446655440001"
REWARD_REDEMPTION_TYPE_ID = "bb0e8400-e29b-41d4-a716-446655440002"

# Reward category IDs
GIFT_CARD_CAT_ID    = "cc0e8400-e29b-41d4-a716-446655440001"
MERCHANDISE_CAT_ID  = "cc0e8400-e29b-41d4-a716-446655440002"
EXPERIENCE_CAT_ID   = "cc0e8400-e29b-41d4-a716-446655440003"
# ─────────────────────────────────────────────

async def print_done():
    print("Done\n")


async def clean_db():
    """Delete all data in reverse-dependency order."""
    print("🧹 Cleaning existing data...")

    # Option 1: Try CASCADE truncate (faster and more thorough)
    try:
        print("   Attempting CASCADE truncate...")
        await db.execute_raw("""
            TRUNCATE TABLE
                audit_log,
                reviews,
                transactions,
                reward_history,
                refresh_tokens,
                employee_roles,
                wallets,
                employees,
                reward_catalog,
                reward_categories,
                transaction_types,
                designations,
                departments,
                department_types,
                roles,
                status_master
            CASCADE
        """)
        print("   ✓ CASCADE truncate successful")
    except Exception as e:
        print(f"   ⚠ CASCADE truncate failed: {e}")
        print("   Falling back to manual deletion...")

        deletion_order = [
            ("audit_log",          db.audit_log),
            ("reviews",            db.reviews),
            ("transactions",       db.transactions),
            ("reward_history",     db.reward_history),
            ("refresh_tokens",     db.refresh_tokens),
            ("employee_roles",     db.employee_roles),
            ("wallets",            db.wallets),
            ("employees",          db.employees),
            ("reward_catalog",     db.reward_catalog),
            ("reward_categories",  db.reward_categories),
            ("transaction_types",  db.transaction_types),
            ("designations",       db.designations),
            ("departments",        db.departments),
            ("department_types",   db.department_types),
            ("roles",              db.roles),
            ("status_master",      db.status_master),
        ]

        for table_name, table in deletion_order:
            try:
                count = await table.delete_many()
                if count > 0:
                    print(f"   ✓ Deleted {count} {table_name} records")
            except Exception as e:
                print(f"   ✗ Could not delete {table_name}: {e}")

    print_done()


async def seed_status_master():
    print("📋 Seeding status_master...")
    now = datetime.now(timezone.utc)

    # GENERAL — ACTIVE (fixed ID used by employees)
    await db.status_master.create(data={
        "status_id":   ACTIVE_STATUS_ID,
        "status_code": "ACTIVE",
        "status_name": "Active",
        "entity_type": "GENERAL",
        "description": "Entity is active",
        "updated_at":  now,
    })

    statuses = [
        # GENERAL
        ("INACTIVE",       "Inactive",  "GENERAL",     "Entity is inactive"),
        # TRANSACTION — APPROVED is used by wallet service for credited transactions
        ("PENDING",        "Pending",   "TRANSACTION",  "Transaction is pending"),
        ("APPROVED",       "Approved",  "TRANSACTION",  "Transaction is approved"),
        ("REJECTED",       "Rejected",  "TRANSACTION",  "Transaction is rejected"),
        # REVIEW
        ("REVIEW_ACTIVE",  "Active",    "REVIEW",       "Review is active and visible"),
        ("REVIEW_DELETED", "Deleted",   "REVIEW",       "Review has been deleted"),
    ]

    for code, name, entity, desc in statuses:
        await db.status_master.create(data={
            "status_code": code,
            "status_name": name,
            "entity_type": entity,
            "description": desc,
            "updated_at":  now,
        })

    print("   ✅ GENERAL:      ACTIVE, INACTIVE")
    print("   ✅ TRANSACTION:  PENDING, APPROVED, REJECTED")
    print("   ✅ REVIEW:       REVIEW_ACTIVE, REVIEW_DELETED")
    print_done()


async def seed_transaction_types():
    print("💳 Seeding transaction_types...")
    now = datetime.now(timezone.utc)

    # CREDIT — awarded to receiver when a review is submitted (rating ≥ 3)
    await db.transaction_types.create(data={
        "type_id":     CREDIT_TYPE_ID,
        "type_name":   "Credit",
        "type_code":   "CREDIT",
        "description": "Points credited to wallet from a performance review",
        "is_credit":   True,
        "updated_at":  now,
    })
    print("   ✅ CREDIT           (is_credit=True)  — review point awards")

    # REWARD_REDEMPTION — deducted when an employee redeems a reward
    await db.transaction_types.create(data={
        "type_id":     REWARD_REDEMPTION_TYPE_ID,
        "type_name":   "Reward Redemption",
        "type_code":   "REWARD_REDEMPTION",
        "description": "Points deducted when an employee redeems a reward from the catalog",
        "is_credit":   False,
        "updated_at":  now,
    })
    print("   ✅ REWARD_REDEMPTION (is_credit=False) — reward catalog redemptions")
    print_done()


async def seed_roles():
    print("👥 Seeding roles...")
    now = datetime.now(timezone.utc)

    for code, name, desc in [
        ("SUPER_ADMIN", "Super Admin", "Full system access"),
        ("HR_ADMIN",    "HR Admin",    "Employee management"),
        ("MANAGER",     "Manager",     "Team management"),
        ("EMPLOYEE",    "Employee",    "Self-service access"),
        ("AUDITOR",     "Auditor",     "Audit read-only access"),
    ]:
        await db.roles.create(data={
            "role_name":   name,
            "role_code":   code,
            "description": desc,
            "updated_at":  now,
        })

    print_done()


async def seed_departments():
    print("🏢 Seeding department types & departments...")
    now = datetime.now(timezone.utc)

    await db.department_types.create(data={
        "department_type_id": TECH_TYPE_ID,
        "type_name":          "Technology",
        "type_code":          "TECH",
        "updated_at":         now,
    })
    await db.department_types.create(data={
        "department_type_id": MGMT_TYPE_ID,
        "type_name":          "Management",
        "type_code":          "MGMT",
        "updated_at":         now,
    })

    await db.departments.create(data={
        "department_id":      ENG_DEPT_ID,
        "department_name":    "Engineering",
        "department_code":    "ENG",
        "department_type_id": TECH_TYPE_ID,
        "updated_at":         now,
    })
    await db.departments.create(data={
        "department_id":      HR_DEPT_ID,
        "department_name":    "Human Resources",
        "department_code":    "HR",
        "department_type_id": MGMT_TYPE_ID,
        "updated_at":         now,
    })

    print_done()


async def seed_designations():
    print("🎖️  Seeding designations...")
    now = datetime.now(timezone.utc)

    await db.designations.create(data={
        "designation_id":   ADMIN_DESIG_ID,
        "designation_name": "System Administrator",
        "designation_code": "SYS_ADMIN",
        "level":            0,
        "updated_at":       now,
    })
    await db.designations.create(data={
        "designation_id":   MGR_DESIG_ID,
        "designation_name": "Engineering Manager",
        "designation_code": "ENG_MGR",
        "level":            2,
        "updated_at":       now,
    })
    await db.designations.create(data={
        "designation_id":   SR_DEV_DESIG_ID,
        "designation_name": "Senior Developer",
        "designation_code": "SR_DEV",
        "level":            3,
        "updated_at":       now,
    })

    print_done()


async def seed_employees():
    print("👤 Seeding employees...")
    print(f"   🔑 Password for ALL accounts: {TEST_PASSWORD}\n")

    hashed = hash_password(TEST_PASSWORD)
    now = datetime.now(timezone.utc)

    # ── Admin ──────────────────────────────────────────────────────────────
    await db.employees.create(data={
        "employee_id":     ADMIN_ID,
        "username":        "admin.user",
        "email":           "admin@company.com",
        "password_hash":   hashed,
        "designation_id":  ADMIN_DESIG_ID,
        "department_id":   HR_DEPT_ID,
        "status_id":       ACTIVE_STATUS_ID,
        "date_of_joining": datetime(2020, 1, 1),
        "created_by":      ADMIN_ID,
        "updated_by":      ADMIN_ID,
        "updated_at":      now,
    })
    await db.wallets.create(data={
        "employee_id":         ADMIN_ID,
        "available_points":    999999,
        "total_earned_points": 999999,
        "created_by":          ADMIN_ID,
        "updated_by":          ADMIN_ID,
        "updated_at":          now,
    })
    print("   ✅ admin.user  → SUPER_ADMIN + HR_ADMIN")

    # ── Manager (Jane) ─────────────────────────────────────────────────────
    await db.employees.create(data={
        "employee_id":     JANE_ID,
        "username":        "jane.smith",
        "email":           "jane.smith@company.com",
        "password_hash":   hashed,
        "designation_id":  MGR_DESIG_ID,
        "department_id":   ENG_DEPT_ID,
        "status_id":       ACTIVE_STATUS_ID,
        "date_of_joining": datetime(2022, 1, 1),
        "created_by":      ADMIN_ID,
        "updated_by":      ADMIN_ID,
        "updated_at":      now,
    })
    await db.wallets.create(data={
        "employee_id":         JANE_ID,
        "available_points":    5000,
        "total_earned_points": 5000,
        "created_by":          ADMIN_ID,
        "updated_by":          ADMIN_ID,
        "updated_at":          now,
    })
    print("   ✅ jane.smith  → MANAGER")

    # ── Employee (John) ────────────────────────────────────────────────────
    await db.employees.create(data={
        "employee_id":     JOHN_ID,
        "username":        "john.doe",
        "email":           "john.doe@company.com",
        "password_hash":   hashed,
        "designation_id":  SR_DEV_DESIG_ID,
        "department_id":   ENG_DEPT_ID,
        "manager_id":      JANE_ID,
        "status_id":       ACTIVE_STATUS_ID,
        "date_of_joining": datetime(2024, 1, 15),
        "created_by":      ADMIN_ID,
        "updated_by":      ADMIN_ID,
        "updated_at":      now,
    })
    await db.wallets.create(data={
        "employee_id":         JOHN_ID,
        "available_points":    1500,
        "redeemed_points":     500,
        "total_earned_points": 2000,
        "version":             5,
        "created_by":          ADMIN_ID,
        "updated_by":          ADMIN_ID,
        "updated_at":          now,
    })
    print("   ✅ john.doe    → EMPLOYEE\n")


async def seed_employee_roles():
    print("🔐 Assigning roles...")
    now = datetime.now(timezone.utc)

    roles = await db.roles.find_many()
    role_map = {r.role_code: r.role_id for r in roles}

    assignments = [
        (ADMIN_ID, "SUPER_ADMIN"),
        (ADMIN_ID, "HR_ADMIN"),
        (JANE_ID,  "MANAGER"),
        (JANE_ID,  "EMPLOYEE"),   # Managers can also create reviews
        (JOHN_ID,  "EMPLOYEE"),
    ]

    for emp_id, role_code in assignments:
        await db.employee_roles.create(data={
            "employee_id": emp_id,
            "role_id":     role_map[role_code],
            "assigned_by": ADMIN_ID,
            "is_active":   True,
            "created_by":  ADMIN_ID,
            "updated_by":  ADMIN_ID,
            "updated_at":  now,
        })
        print(f"   ✅ {emp_id[:8]}... → {role_code}")

    print()


async def seed_reward_categories():
    print("🏷️  Seeding reward_categories...")
    now = datetime.now(timezone.utc)

    categories = [
        (GIFT_CARD_CAT_ID,   "Gift Cards",    "GIFT_CARD",   "Digital and physical gift cards"),
        (MERCHANDISE_CAT_ID, "Merchandise",   "MERCHANDISE", "Company branded merchandise and physical items"),
        (EXPERIENCE_CAT_ID,  "Experiences",   "EXPERIENCE",  "Events, courses, and experiences"),
    ]

    for cat_id, name, code, desc in categories:
        await db.reward_categories.create(data={
            "category_id":   cat_id,
            "category_name": name,
            "category_code": code,
            "description":   desc,
            "is_active":     True,
            "employees_reward_categories_created_byToemployees": {
                "connect": {"employee_id": ADMIN_ID}
            },
            "employees_reward_categories_updated_byToemployees": {
                "connect": {"employee_id": ADMIN_ID}
            },
            "updated_at": now,
        })
        print(f"   ✅ {code}")

    print_done()


async def seed_reward_catalog():
    print("🎁 Seeding reward_catalog...")
    now = datetime.now(timezone.utc)

    items = [
        # (name, code, description, category_id, default_pts, min_pts, max_pts, stock)
        (
            "Amazon Gift Card $10",
            "REW-AMZ-10",
            "Amazon digital gift card worth $10 USD",
            GIFT_CARD_CAT_ID,
            100, 100, 100, 50,
        ),
        (
            "Amazon Gift Card $25",
            "REW-AMZ-25",
            "Amazon digital gift card worth $25 USD",
            GIFT_CARD_CAT_ID,
            250, 250, 250, 30,
        ),
        (
            "Company T-Shirt",
            "REW-MERCH-SHIRT",
            "Premium company branded T-shirt",
            MERCHANDISE_CAT_ID,
            200, 200, 200, 100,
        ),
        (
            "Company Hoodie",
            "REW-MERCH-HOODIE",
            "Premium company branded hoodie",
            MERCHANDISE_CAT_ID,
            400, 400, 400, 40,
        ),
        (
            "Udemy Course Voucher",
            "REW-LEARN-UDEMY",
            "One Udemy course of your choice",
            EXPERIENCE_CAT_ID,
            300, 300, 300, 20,
        ),
        (
            "Team Lunch Voucher",
            "REW-EXP-LUNCH",
            "Lunch for you and your team (up to 5 people)",
            EXPERIENCE_CAT_ID,
            500, 500, 500, 15,
        ),
    ]

    for name, code, desc, cat_id, default_pts, min_pts, max_pts, stock in items:
        # Use relation connect for category_id (Prisma Python requires this)
        # available_stock is updated via raw SQL after creation since
        # some generated clients don't expose it as a writable scalar
        item = await db.reward_catalog.create(data={
            "reward_name":    name,
            "reward_code":    code,
            "description":    desc,
            "default_points": default_pts,
            "min_points":     min_pts,
            "max_points":     max_pts,
            "is_active":      True,
            "reward_categories": {
                "connect": {"category_id": cat_id}
            },
            "employees_reward_catalog_created_byToemployees": {
                "connect": {"employee_id": ADMIN_ID}
            },
            "employees_reward_catalog_updated_byToemployees": {
                "connect": {"employee_id": ADMIN_ID}
            },
            "updated_at": now,
        })
        # Set available_stock directly via raw SQL
        await db.execute_raw(
            f"UPDATE reward_catalog SET available_stock = {stock} WHERE catalog_id = '{item.catalog_id}'"
        )
        print(f"   ✅ {code:25s}  {default_pts} pts  stock: {stock}")

    print_done()


async def main():
    await db.connect()

    try:
        print("=" * 60)
        print("🌱 EMPLOYEE REWARDS SYSTEM — DATABASE SEED")
        print("=" * 60)
        print()

        await clean_db()
        await seed_status_master()
        await seed_transaction_types()   # ← NEW: CREDIT + REWARD_REDEMPTION
        await seed_roles()
        await seed_departments()
        await seed_designations()
        await seed_employees()
        await seed_employee_roles()
        await seed_reward_categories()   # ← NEW: Gift Cards, Merchandise, Experiences
        await seed_reward_catalog()      # ← NEW: 6 sample reward items

        print("=" * 60)
        print("🎉 SEED COMPLETE!")
        print("=" * 60)
        print()
        print("📝 Login credentials (all share the same password):")
        print()
        print("   username: admin.user  |  roles: SUPER_ADMIN, HR_ADMIN")
        print("   username: jane.smith  |  roles: MANAGER, EMPLOYEE")
        print("   username: john.doe    |  role:  EMPLOYEE")
        print()
        print(f"   password (all): {TEST_PASSWORD}")
        print()
        print("💳 Transaction types seeded:")
        print("   CREDIT           (is_credit=True)  — auto-credited on review")
        print("   REWARD_REDEMPTION (is_credit=False) — deducted on reward redemption")
        print()
        print("🎁 Reward catalog: 6 items across 3 categories")
        print()
        print("🚀 Auth Service:        http://127.0.0.1:8001/v1/docs")
        print("🚀 Employee Service:    http://127.0.0.1:8002/v1/docs")
        print("🚀 Wallet Service:      http://127.0.0.1:8004/v1/docs")
        print("🚀 Recognition Service: http://127.0.0.1:8005/v1/docs")
        print("🚀 Rewards Service:     http://127.0.0.1:8006/v1/docs")
        print()

    except Exception as e:
        print(f"\n❌ Seed failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())