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


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — fixed UUIDs make re-runs idempotent and cross-service references safe
# ─────────────────────────────────────────────────────────────────────────────

TEST_PASSWORD = "Password123!"

# Employees
ADMIN_ID         = "110e8400-e29b-41d4-a716-446655440000"
JANE_ID          = "880e8400-e29b-41d4-a716-446655440000"
JOHN_ID          = "550e8400-e29b-41d4-a716-446655440000"

# Status
ACTIVE_STATUS_ID = "990e8400-e29b-41d4-a716-446655440000"

# Departments
ENG_DEPT_ID      = "770e8400-e29b-41d4-a716-446655440000"
HR_DEPT_ID       = "330e8400-e29b-41d4-a716-446655440000"
TECH_TYPE_ID     = "aa0e8400-e29b-41d4-a716-446655440001"
MGMT_TYPE_ID     = "aa0e8400-e29b-41d4-a716-446655440002"

# Designations
SR_DEV_DESIG_ID  = "660e8400-e29b-41d4-a716-446655440000"
MGR_DESIG_ID     = "660e8400-e29b-41d4-a716-446655440001"
ADMIN_DESIG_ID   = "660e8400-e29b-41d4-a716-446655440002"

# Transaction types
CREDIT_TYPE_ID            = "bb0e8400-e29b-41d4-a716-446655440001"
REWARD_REDEMPTION_TYPE_ID = "bb0e8400-e29b-41d4-a716-446655440002"

# Reward categories
GIFT_CARD_CAT_ID    = "cc0e8400-e29b-41d4-a716-446655440001"
MERCHANDISE_CAT_ID  = "cc0e8400-e29b-41d4-a716-446655440002"
EXPERIENCE_CAT_ID   = "cc0e8400-e29b-41d4-a716-446655440003"

# Review categories
RC_TEAMWORK_ID      = "dd0e8400-e29b-41d4-a716-446655440001"
RC_INNOVATION_ID    = "dd0e8400-e29b-41d4-a716-446655440002"
RC_LEADERSHIP_ID    = "dd0e8400-e29b-41d4-a716-446655440003"
RC_CUST_IMPACT_ID   = "dd0e8400-e29b-41d4-a716-446655440004"
RC_OWNERSHIP_ID     = "dd0e8400-e29b-41d4-a716-446655440005"
RC_TECH_EXCEL_ID    = "dd0e8400-e29b-41d4-a716-446655440006"
RC_CULTURE_ID       = "dd0e8400-e29b-41d4-a716-446655440007"

# Seasonal multipliers
SM_Q1_ID = "ee0e8400-e29b-41d4-a716-446655440001"
SM_Q2_ID = "ee0e8400-e29b-41d4-a716-446655440002"
SM_Q3_ID = "ee0e8400-e29b-41d4-a716-446655440003"
SM_Q4_ID = "ee0e8400-e29b-41d4-a716-446655440004"

# Points config
PC_DECAY_RATE_ID = "ff0e8400-e29b-41d4-a716-446655440001"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def print_done():
    print("   Done ✓\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLEAN
# ─────────────────────────────────────────────────────────────────────────────

async def clean_db():
    """Delete all data in reverse-dependency order."""
    print("🧹 Cleaning existing data...")

    try:
        print("   Attempting CASCADE truncate...")
        await db.execute_raw("""
            TRUNCATE TABLE
                audit_log,
                notifications,
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
                status_master,
                review_categories,
                seasonal_multipliers,
                points_config
            CASCADE
        """)
        print("   ✓ CASCADE truncate successful")
    except Exception as e:
        print(f"   ⚠ CASCADE truncate failed: {e}")
        print("   Falling back to manual deletion...")

        deletion_order = [
            ("audit_log",            db.audit_log),
            ("notifications",        db.notifications),
            ("reviews",              db.reviews),
            ("transactions",         db.transactions),
            ("reward_history",       db.reward_history),
            ("refresh_tokens",       db.refresh_tokens),
            ("employee_roles",       db.employee_roles),
            ("wallets",              db.wallets),
            ("employees",            db.employees),
            ("reward_catalog",       db.reward_catalog),
            ("reward_categories",    db.reward_categories),
            ("review_categories",    db.review_categories),
            ("seasonal_multipliers", db.seasonal_multipliers),
            ("points_config",        db.points_config),
            ("transaction_types",    db.transaction_types),
            ("designations",         db.designations),
            ("departments",          db.departments),
            ("department_types",     db.department_types),
            ("roles",                db.roles),
            ("status_master",        db.status_master),
        ]

        for table_name, table in deletion_order:
            try:
                count = await table.delete_many()
                if count > 0:
                    print(f"   ✓ Deleted {count} {table_name} records")
            except Exception as ex:
                print(f"   ✗ Could not delete {table_name}: {ex}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# STATUS MASTER
# ─────────────────────────────────────────────────────────────────────────────

async def seed_status_master():
    print("📋 Seeding status_master...")
    now = datetime.now(timezone.utc)

    await db.status_master.create(data={
        "status_id":   ACTIVE_STATUS_ID,
        "status_code": "ACTIVE",
        "status_name": "Active",
        "entity_type": "GENERAL",
        "description": "Entity is active",
        "updated_at":  now,
    })

    statuses = [
        ("INACTIVE",       "Inactive",  "GENERAL",      "Entity is inactive"),
        ("PENDING",        "Pending",   "TRANSACTION",  "Transaction is pending"),
        ("APPROVED",       "Approved",  "TRANSACTION",  "Transaction is approved"),
        ("REJECTED",       "Rejected",  "TRANSACTION",  "Transaction is rejected"),
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
    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION TYPES
# ─────────────────────────────────────────────────────────────────────────────

async def seed_transaction_types():
    print("💳 Seeding transaction_types...")
    now = datetime.now(timezone.utc)

    await db.transaction_types.create(data={
        "type_id":     CREDIT_TYPE_ID,
        "type_name":   "Credit",
        "type_code":   "CREDIT",
        "description": "Points credited to wallet from a performance review",
        "is_credit":   True,
        "updated_at":  now,
    })
    print("   ✅ CREDIT            (is_credit=True)  — review point awards")

    await db.transaction_types.create(data={
        "type_id":     REWARD_REDEMPTION_TYPE_ID,
        "type_name":   "Reward Redemption",
        "type_code":   "REWARD_REDEMPTION",
        "description": "Points deducted when an employee redeems a reward from the catalog",
        "is_credit":   False,
        "updated_at":  now,
    })
    print("   ✅ REWARD_REDEMPTION  (is_credit=False) — reward catalog redemptions")
    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# ROLES
# ─────────────────────────────────────────────────────────────────────────────

async def seed_roles():
    print("👥 Seeding roles (with reviewer_weight)...")
    now = datetime.now(timezone.utc)

    roles = [
        ("SUPER_ADMIN", "Super Admin", "Full system access",     2.0),
        ("HR_ADMIN",    "HR Admin",    "Employee management",    2.0),
        ("MANAGER",     "Manager",     "Team management",        1.5),
        ("EMPLOYEE",    "Employee",    "Self-service access",    1.0),
        ("AUDITOR",     "Auditor",     "Audit read-only access", 1.0),
    ]

    for code, name, desc, weight in roles:
        await db.roles.create(data={
            "role_name":       name,
            "role_code":       code,
            "description":     desc,
            "reviewer_weight": weight,
            "updated_at":      now,
        })
        print(f"   ✅ {code:15s}  reviewer_weight={weight}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENTS
# ─────────────────────────────────────────────────────────────────────────────

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
    await db.department_types.create(data={
        "type_name":  "Operations",
        "type_code":  "OPS",
        "updated_at": now,
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
    await db.departments.create(data={
        "department_name":    "Product",
        "department_code":    "PROD",
        "department_type_id": TECH_TYPE_ID,
        "updated_at":         now,
    })

    print("   ✅ Types:  TECH, MGMT, OPS")
    print("   ✅ Depts:  Engineering, Human Resources, Product")
    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# DESIGNATIONS
# ─────────────────────────────────────────────────────────────────────────────

async def seed_designations():
    print("🎖️  Seeding designations...")
    now = datetime.now(timezone.utc)

    designations = [
        (ADMIN_DESIG_ID,  "System Administrator", "SYS_ADMIN", 0),
        (MGR_DESIG_ID,    "Engineering Manager",  "ENG_MGR",   2),
        (SR_DEV_DESIG_ID, "Senior Developer",     "SR_DEV",    3),
        (None,            "Junior Developer",     "JR_DEV",    5),
        (None,            "Product Manager",      "PROD_MGR",  2),
    ]

    for desig_id, name, code, level in designations:
        data = {
            "designation_name": name,
            "designation_code": code,
            "level":            level,
            "updated_at":       now,
        }
        if desig_id:
            data["designation_id"] = desig_id
        await db.designations.create(data=data)
        print(f"   ✅ {code:12s}  level={level}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEES + WALLETS
# Dates of birth set so the celebration worker can be tested immediately:
#   - admin.user  → birthday TODAY (any past year), work anniversary today
#   - jane.smith  → birthday in a week (for future testing)
#   - john.doe    → birthday on a fixed past date (no celebration today)
# ─────────────────────────────────────────────────────────────────────────────

async def seed_employees():
    print("👤 Seeding employees & wallets...")
    print(f"   🔑 Password for ALL accounts: {TEST_PASSWORD}\n")

    hashed = hash_password(TEST_PASSWORD)
    now    = datetime.now(timezone.utc)
    today  = now.date()

    # ── Admin ──────────────────────────────────────────────────────────────
    # date_of_birth = TODAY's month/day, 30 years ago  → birthday fires today
    # date_of_joining = same month/day, 4 years ago    → anniversary fires today
    admin_dob = today.replace(year=today.year - 30)
    admin_doj = today.replace(year=today.year - 4)
    await db.employees.create(data={
        "employee_id":     ADMIN_ID,
        "username":        "admin.user",
        "email":           "admin@company.com",
        "password_hash":   hashed,
        "designation_id":  ADMIN_DESIG_ID,
        "department_id":   HR_DEPT_ID,
        "status_id":       ACTIVE_STATUS_ID,
        "date_of_joining": datetime(admin_doj.year, admin_doj.month, admin_doj.day),
        "date_of_birth":   datetime(admin_dob.year, admin_dob.month, admin_dob.day),
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
    print(f"   ✅ admin.user   dob={admin_dob}  doj={admin_doj}  🎂🏆 BOTH fire today")

    # ── Manager (Jane) ─────────────────────────────────────────────────────
    # date_of_birth = 7 days from now (month/day), in the past year
    # date_of_joining = 2022-01-01 → anniversary only fires on Jan 1
    from datetime import timedelta
    jane_bday_future = today + timedelta(days=7)
    jane_dob = jane_bday_future.replace(year=today.year - 28)
    await db.employees.create(data={
        "employee_id":     JANE_ID,
        "username":        "jane.smith",
        "email":           "jane.smith@company.com",
        "password_hash":   hashed,
        "designation_id":  MGR_DESIG_ID,
        "department_id":   ENG_DEPT_ID,
        "status_id":       ACTIVE_STATUS_ID,
        "date_of_joining": datetime(2022, 1, 1),
        "date_of_birth":   datetime(jane_dob.year, jane_dob.month, jane_dob.day),
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
    print(f"   ✅ jane.smith   dob={jane_dob}  doj=2022-01-01  🎂 birthday in 7 days")

    # ── Employee (John) ────────────────────────────────────────────────────
    # date_of_birth = fixed past date → no celebration today
    # date_of_joining = 2024-01-15 → anniversary fires on Jan 15
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
        "date_of_birth":   datetime(1995, 6, 20),
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
    print(f"   ✅ john.doe     dob=1995-06-20  doj=2024-01-15  no celebration today")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEE ROLES
# ─────────────────────────────────────────────────────────────────────────────

async def seed_employee_roles():
    print("🔐 Assigning employee roles...")
    now = datetime.now(timezone.utc)

    roles    = await db.roles.find_many()
    role_map = {r.role_code: r.role_id for r in roles}

    assignments = [
        (ADMIN_ID, "SUPER_ADMIN"),
        (ADMIN_ID, "HR_ADMIN"),
        (JANE_ID,  "MANAGER"),
        (JANE_ID,  "EMPLOYEE"),
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
        print(f"   ✅ {emp_id[:8]}...  →  {role_code}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# REWARD CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────

async def seed_reward_categories():
    print("🏷️  Seeding reward_categories...")
    now = datetime.now(timezone.utc)

    categories = [
        (GIFT_CARD_CAT_ID,   "Gift Cards",   "GIFT_CARD",   "Digital and physical gift cards"),
        (MERCHANDISE_CAT_ID, "Merchandise",  "MERCHANDISE", "Company branded merchandise and physical items"),
        (EXPERIENCE_CAT_ID,  "Experiences",  "EXPERIENCE",  "Events, courses, and experiences"),
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

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# REWARD CATALOG
# ─────────────────────────────────────────────────────────────────────────────

async def seed_reward_catalog():
    print("🎁 Seeding reward_catalog...")
    now = datetime.now(timezone.utc)

    items = [
        ("Amazon Gift Card $10",  "REW-AMZ-10",       "Amazon digital gift card worth $10 USD",           GIFT_CARD_CAT_ID,   100, 100, 100, 50),
        ("Amazon Gift Card $25",  "REW-AMZ-25",       "Amazon digital gift card worth $25 USD",           GIFT_CARD_CAT_ID,   250, 250, 250, 30),
        ("Company T-Shirt",       "REW-MERCH-SHIRT",  "Premium company branded T-shirt",                  MERCHANDISE_CAT_ID, 200, 200, 200, 100),
        ("Company Hoodie",        "REW-MERCH-HOODIE", "Premium company branded hoodie",                   MERCHANDISE_CAT_ID, 400, 400, 400, 40),
        ("Udemy Course Voucher",  "REW-LEARN-UDEMY",  "One Udemy course of your choice",                  EXPERIENCE_CAT_ID,  300, 300, 300, 20),
        ("Team Lunch Voucher",    "REW-EXP-LUNCH",    "Lunch for you and your team (up to 5 people)",     EXPERIENCE_CAT_ID,  500, 500, 500, 15),
    ]

    for name, code, desc, cat_id, default_pts, min_pts, max_pts, stock in items:
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
        await db.execute_raw(
            f"UPDATE reward_catalog SET available_stock = {stock} WHERE catalog_id = '{item.catalog_id}'"
        )
        print(f"   ✅ {code:25s}  {default_pts} pts   stock: {stock}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────

async def seed_review_categories():
    print("⭐ Seeding review_categories (points multipliers)...")
    now = datetime.now(timezone.utc)

    categories = [
        (RC_TEAMWORK_ID,    "TEAMWORK",             "Teamwork",             1.0, "Collaboration and team contribution"),
        (RC_INNOVATION_ID,  "INNOVATION",           "Innovation",           1.4, "Creative problem-solving and novel ideas"),
        (RC_LEADERSHIP_ID,  "LEADERSHIP",           "Leadership",           1.3, "Guiding and inspiring others"),
        (RC_CUST_IMPACT_ID, "CUSTOMER_IMPACT",      "Customer Impact",      1.2, "Delivering measurable value to customers"),
        (RC_OWNERSHIP_ID,   "OWNERSHIP",            "Ownership",            1.1, "Taking end-to-end responsibility for outcomes"),
        (RC_TECH_EXCEL_ID,  "TECHNICAL_EXCELLENCE", "Technical Excellence", 1.3, "High-quality technical output and craftsmanship"),
        (RC_CULTURE_ID,     "CULTURE_CHAMPION",     "Culture Champion",     1.1, "Embodying and actively promoting company values"),
    ]

    for cat_id, code, name, mult, desc in categories:
        await db.review_categories.create(data={
            "category_id":   cat_id,
            "category_code": code,
            "category_name": name,
            "multiplier":    mult,
            "description":   desc,
            "is_active":     True,
            "created_by":    ADMIN_ID,
            "updated_by":    ADMIN_ID,
            "updated_at":    now,
        })
        print(f"   ✅ {code:25s}  multiplier={mult}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# SEASONAL MULTIPLIERS
# ─────────────────────────────────────────────────────────────────────────────

async def seed_seasonal_multipliers():
    print("🗓️  Seeding seasonal_multipliers...")
    now = datetime.now(timezone.utc)

    seasons = [
        (SM_Q1_ID, 1, "Q1 – Standard",       1.0),
        (SM_Q2_ID, 2, "Q2 – Mid-Year Push",   1.1),
        (SM_Q3_ID, 3, "Q3 – Standard",        1.0),
        (SM_Q4_ID, 4, "Q4 – Year-End Sprint", 1.2),
    ]

    for sm_id, quarter, label, mult in seasons:
        await db.seasonal_multipliers.create(data={
            "seasonal_multiplier_id": sm_id,
            "quarter":                quarter,
            "label":                  label,
            "multiplier":             mult,
            "effective_from":         None,
            "effective_to":           None,
            "created_by":             ADMIN_ID,
            "updated_by":             ADMIN_ID,
            "updated_at":             now,
        })
        print(f"   ✅ Q{quarter}  {label:28s}  multiplier={mult}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# POINTS CONFIG
# ─────────────────────────────────────────────────────────────────────────────

async def seed_points_config():
    print("⚙️  Seeding points_config (engine constants)...")
    now = datetime.now(timezone.utc)

    configs = [
        (PC_DECAY_RATE_ID, "DECAY_RATE", 0.9,  "10 % quarterly decay applied to effective_points on historical reviews"),
        (None,             "MAX_POINTS_PER_REVIEW", 500.0, "Hard cap on points awarded from a single review"),
        (None,             "MIN_RATING",            1.0,   "Minimum allowed rating value on a review"),
    ]

    for cfg_id, key, value, desc in configs:
        data = {
            "config_key":     key,
            "config_value":   value,
            "description":    desc,
            "effective_from": None,
            "created_by":     ADMIN_ID,
            "updated_by":     ADMIN_ID,
            "updated_at":     now,
        }
        if cfg_id:
            data["config_id"] = cfg_id
        await db.points_config.create(data=data)
        print(f"   ✅ {key:25s}  value={value}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# Three representative rows — one per type — so the notifications endpoints
# and the celebration worker logic can be verified immediately in Swagger.
#
# Row 1 (REVIEW)       — unread, no email sent  → visible in GET /notifications
# Row 2 (REWARD)       — read,   email sent      → visible with unread_only=false
# Row 3 (CELEBRATION)  — unread, email sent      → simulates a past birthday hit
# ─────────────────────────────────────────────────────────────────────────────

async def seed_notifications():
    print("🔔 Seeding notifications...")
    now = datetime.now(timezone.utc)

    notifications = [
        # (employee_id, title, message, type, is_read, email_sent, read_at)
        (
            JOHN_ID,
            "You received a new review",
            "Jane Smith left you a 5-star review for Technical Excellence. Great work this sprint!",
            "REVIEW",
            False,
            False,
            None,
        ),
        (
            JANE_ID,
            "Reward redeemed: Amazon Gift Card $25",
            "Your redemption of 250 points for an Amazon Gift Card $25 has been approved.",
            "REWARD",
            True,
            True,
            now,
        ),
        (
            ADMIN_ID,
            "🎂 Happy Birthday, admin.user! — BIRTHDAY",
            "Wishing admin.user a very happy birthday! 🎂",
            "CELEBRATION",
            False,
            True,
            None,
        ),
        # Extra rows so each employee has at least one notification
        (
            JOHN_ID,
            "Welcome to the rewards system",
            "Your account is set up and your wallet is ready. Start earning points by receiving reviews!",
            "SYSTEM",
            True,
            True,
            now,
        ),
        (
            JANE_ID,
            "New review submitted",
            "You submitted a performance review for john.doe. Points will be credited once approved.",
            "REVIEW",
            False,
            False,
            None,
        ),
        (
            ADMIN_ID,
            "🏆 Happy 4th Work Anniversary, admin.user! — WORK_ANNIVERSARY",
            "Congratulations to admin.user on their 4-year work anniversary! 🏆",
            "CELEBRATION",
            False,
            True,
            None,
        ),
    ]

    for emp_id, title, message, ntype, is_read, email_sent, read_at in notifications:
        data = {
            "employee_id": emp_id,
            "title":       title,
            "message":     message,
            "type":        ntype,
            "is_read":     is_read,
            "email_sent":  email_sent,
            "created_at":  now,
        }
        if read_at:
            data["read_at"] = read_at
        await db.notifications.create(data=data)
        status_icon = "✅ read  " if is_read else "🔵 unread"
        print(f"   {status_icon}  [{ntype:12s}]  {title[:55]}")

    await print_done()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    await db.connect()

    try:
        print()
        print("=" * 65)
        print("🌱  EMPLOYEE REWARDS SYSTEM — DATABASE SEED")
        print("=" * 65)
        print()

        await clean_db()
        await seed_status_master()
        await seed_transaction_types()
        await seed_roles()
        await seed_departments()
        await seed_designations()
        await seed_employees()
        await seed_employee_roles()
        await seed_reward_categories()
        await seed_reward_catalog()
        await seed_review_categories()
        await seed_seasonal_multipliers()
        await seed_points_config()
        await seed_notifications()       # ← NEW

        print("=" * 65)
        print("🎉  SEED COMPLETE!")
        print("=" * 65)
        print()
        print("📝 Login credentials (all share the same password):")
        print()
        print(f"   {'username':<15}  roles")
        print(f"   {'─'*15}  {'─'*30}")
        print(f"   {'admin.user':<15}  SUPER_ADMIN, HR_ADMIN")
        print(f"   {'jane.smith':<15}  MANAGER, EMPLOYEE")
        print(f"   {'john.doe':<15}  EMPLOYEE")
        print()
        print(f"   password (all): {TEST_PASSWORD}")
        print()
        print("🔔 Notifications seeded (6 rows — test in Swagger):")
        print("   admin.user  →  CELEBRATION ×2 (birthday + anniversary, both fire TODAY)")
        print("   jane.smith  →  REWARD (read), REVIEW (unread)")
        print("   john.doe    →  REVIEW (unread), SYSTEM (read)")
        print()
        print("🎂 Celebration worker test setup:")
        print("   admin.user  date_of_birth  = TODAY (30 yrs ago)  → fires on next worker tick")
        print("   admin.user  date_of_joining = TODAY (4 yrs ago)  → fires on next worker tick")
        print("   jane.smith  date_of_birth  = TODAY+7 days        → fires in 7 days")
        print("   john.doe    date_of_birth  = 1995-06-20          → no celebration today")
        print()
        print("⭐ Review categories:  7 categories with multipliers 1.0–1.4")
        print("🗓️  Seasonal multipliers:  Q1×1.0 | Q2×1.1 | Q3×1.0 | Q4×1.2")
        print("⚙️  Points config:  DECAY_RATE=0.9 | MAX_POINTS_PER_REVIEW=500 | MIN_RATING=1")
        print("👥 Role weights:  SUPER_ADMIN/HR_ADMIN=2.0 | MANAGER=1.5 | EMPLOYEE=1.0")
        print("💳 Transaction types:  CREDIT | REWARD_REDEMPTION")
        print("🎁 Reward catalog:  6 items across 3 categories")
        print()
        print("🚀 Auth Service:         http://127.0.0.1:8001/v1/docs")
        print("🚀 Employee Service:     http://127.0.0.1:8002/v1/docs")
        print("🚀 Wallet Service:       http://127.0.0.1:8004/v1/docs")
        print("🚀 Recognition Service:  http://127.0.0.1:8005/v1/docs")
        print("🚀 Rewards Service:      http://127.0.0.1:8006/v1/docs")
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