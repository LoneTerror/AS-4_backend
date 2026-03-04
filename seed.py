"""
Complete database seeding script for Employee Rewards System.
Self-contained — seeds everything from scratch in the correct order.

Run with:
    python seed.py

What's seeded (matches schema.prisma exactly):
    status_master          — GENERAL, TRANSACTION, REVIEW statuses
    transaction_types      — CREDIT, REWARD_REDEMPTION
    roles                  — SUPER_ADMIN, HR_ADMIN, MANAGER, EMPLOYEE, AUDITOR
    department_types       — TECH, MGMT  (with created_by / updated_by)
    departments            — ENG, HR     (with created_by / updated_by)
    designations           — SYS_ADMIN, ENG_MGR, SR_DEV  (with created_by / updated_by)
    points_config          — BASE_POINTS_PER_STAR, MAX_POINTS_PER_REVIEW
    review_categories      — OWNERSHIP, INNOVATION, COLLABORATION, LEADERSHIP
    seasonal_multipliers   — Q1–Q4
    employees              — admin, jane, john, arijit, shubrajit, prasun (all DOBs = today)
    wallets                — one per employee
    employee_roles         — role assignments
    reward_categories      — GIFT_CARD, MERCHANDISE, EXPERIENCE
    reward_catalog         — 6 items
    transactions           — sample CREDIT transactions for john
    reward_history         — sample redemption for john
    reviews                — sample review jane→john with category tags
    audit_log              — sample audit entries
"""
import asyncio
import uuid
from datetime import date, datetime, timezone, timedelta

from src.prisma.client import db
from src.core.security import hash_password


# ─────────────────────────────────────────────────────────────────────────────
# FIXED IDs  — keep stable so re-seeding is idempotent
# ─────────────────────────────────────────────────────────────────────────────
TEST_PASSWORD = "Password123!"

# Today's date — all DOBs set to today so birthday notifications fire
TODAY = date.today()

# Employees
ADMIN_ID      = "110e8400-e29b-41d4-a716-446655440000"
JANE_ID       = "880e8400-e29b-41d4-a716-446655440000"
JOHN_ID       = "550e8400-e29b-41d4-a716-446655440000"
ARIJIT_ID     = "aa1e8400-e29b-41d4-a716-446655440001"
SHUBRAJIT_ID  = "bb1e8400-e29b-41d4-a716-446655440002"
PRASUN_ID     = "cc1e8400-e29b-41d4-a716-446655440003"

# Status
ACTIVE_STATUS_ID      = "990e8400-e29b-41d4-a716-446655440000"
INACTIVE_STATUS_ID    = "990e8400-e29b-41d4-a716-446655440001"
TXN_PENDING_ID        = "990e8400-e29b-41d4-a716-446655440002"
TXN_APPROVED_ID       = "990e8400-e29b-41d4-a716-446655440003"
TXN_REJECTED_ID       = "990e8400-e29b-41d4-a716-446655440004"
REVIEW_ACTIVE_ID      = "990e8400-e29b-41d4-a716-446655440005"
REVIEW_DELETED_ID     = "990e8400-e29b-41d4-a716-446655440006"

# Departments
TECH_TYPE_ID = "aa0e8400-e29b-41d4-a716-446655440001"
MGMT_TYPE_ID = "aa0e8400-e29b-41d4-a716-446655440002"
ENG_DEPT_ID  = "770e8400-e29b-41d4-a716-446655440000"
HR_DEPT_ID   = "330e8400-e29b-41d4-a716-446655440000"

# Designations
SR_DEV_DESIG_ID = "660e8400-e29b-41d4-a716-446655440000"
MGR_DESIG_ID    = "660e8400-e29b-41d4-a716-446655440001"
ADMIN_DESIG_ID  = "660e8400-e29b-41d4-a716-446655440002"

# Transaction types
CREDIT_TYPE_ID            = "bb0e8400-e29b-41d4-a716-446655440001"
REWARD_REDEMPTION_TYPE_ID = "bb0e8400-e29b-41d4-a716-446655440002"

# Reward categories
GIFT_CARD_CAT_ID   = "cc0e8400-e29b-41d4-a716-446655440001"
MERCHANDISE_CAT_ID = "cc0e8400-e29b-41d4-a716-446655440002"
EXPERIENCE_CAT_ID  = "cc0e8400-e29b-41d4-a716-446655440003"

# Review categories
RC_OWNERSHIP_ID      = "dd0e8400-e29b-41d4-a716-446655440001"
RC_INNOVATION_ID     = "dd0e8400-e29b-41d4-a716-446655440002"
RC_COLLAB_ID         = "dd0e8400-e29b-41d4-a716-446655440003"
RC_LEADERSHIP_ID     = "dd0e8400-e29b-41d4-a716-446655440004"

# Points config
PC_BASE_ID = "ee0e8400-e29b-41d4-a716-446655440001"
PC_MAX_ID  = "ee0e8400-e29b-41d4-a716-446655440002"

# Seasonal multipliers
SM_Q1_ID = "ff0e8400-e29b-41d4-a716-446655440001"
SM_Q2_ID = "ff0e8400-e29b-41d4-a716-446655440002"
SM_Q3_ID = "ff0e8400-e29b-41d4-a716-446655440003"
SM_Q4_ID = "ff0e8400-e29b-41d4-a716-446655440004"

NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def uid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# CLEAN
# ─────────────────────────────────────────────────────────────────────────────
async def clean_db():
    print("🧹 Cleaning existing data...")
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
                points_config,
                seasonal_multipliers,
                designations,
                departments,
                department_types,
                roles,
                status_master
            CASCADE
        """)
        print("   ✓ CASCADE truncate successful\n")
    except Exception as e:
        print(f"   ⚠ CASCADE truncate failed: {e}")
        deletion_order = [
            ("audit_log",             db.audit_log),
            ("review_category_tags",  db.review_category_tags),
            ("reviews",               db.reviews),
            ("transactions",          db.transactions),
            ("reward_history",        db.reward_history),
            ("refresh_tokens",        db.refresh_tokens),
            ("employee_roles",        db.employee_roles),
            ("wallets",               db.wallets),
            ("notifications",         db.notifications),
            ("employees",             db.employees),
            ("reward_catalog",        db.reward_catalog),
            ("reward_categories",     db.reward_categories),
            ("transaction_types",     db.transaction_types),
            ("review_categories",     db.review_categories),
            ("points_config",         db.points_config),
            ("seasonal_multipliers",  db.seasonal_multipliers),
            ("designations",          db.designations),
            ("departments",           db.departments),
            ("department_types",      db.department_types),
            ("roles",                 db.roles),
            ("status_master",         db.status_master),
        ]
        for name, table in deletion_order:
            try:
                count = await table.delete_many()
                if count:
                    print(f"   ✓ Deleted {count} {name} rows")
            except Exception as ex:
                print(f"   ✗ Could not delete {name}: {ex}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# STATUS MASTER
# ─────────────────────────────────────────────────────────────────────────────
async def seed_status_master():
    print("📋 Seeding status_master...")
    rows = [
        (ACTIVE_STATUS_ID,   "ACTIVE",         "Active",    "GENERAL",     "Entity is active"),
        (INACTIVE_STATUS_ID, "INACTIVE",       "Inactive",  "GENERAL",     "Entity is inactive"),
        (TXN_PENDING_ID,     "PENDING",        "Pending",   "TRANSACTION", "Transaction is pending"),
        (TXN_APPROVED_ID,    "APPROVED",       "Approved",  "TRANSACTION", "Transaction is approved"),
        (TXN_REJECTED_ID,    "REJECTED",       "Rejected",  "TRANSACTION", "Transaction is rejected"),
        (REVIEW_ACTIVE_ID,   "REVIEW_ACTIVE",  "Active",    "REVIEW",      "Review is active and visible"),
        (REVIEW_DELETED_ID,  "REVIEW_DELETED", "Deleted",   "REVIEW",      "Review has been soft-deleted"),
    ]
    for status_id, code, name, entity, desc in rows:
        await db.status_master.create(data={
            "status_id":   status_id,
            "status_code": code,
            "status_name": name,
            "entity_type": entity,
            "description": desc,
            "updated_at":  NOW,
        })
    print("   ✅ GENERAL:      ACTIVE, INACTIVE")
    print("   ✅ TRANSACTION:  PENDING, APPROVED, REJECTED")
    print("   ✅ REVIEW:       REVIEW_ACTIVE, REVIEW_DELETED\n")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION TYPES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_transaction_types():
    print("💳 Seeding transaction_types...")
    await db.transaction_types.create(data={
        "type_id":     CREDIT_TYPE_ID,
        "type_name":   "Credit",
        "type_code":   "CREDIT",
        "description": "Points credited to wallet from a performance review",
        "is_credit":   True,
        "updated_at":  NOW,
    })
    await db.transaction_types.create(data={
        "type_id":     REWARD_REDEMPTION_TYPE_ID,
        "type_name":   "Reward Redemption",
        "type_code":   "REWARD_REDEMPTION",
        "description": "Points deducted when an employee redeems a reward",
        "is_credit":   False,
        "updated_at":  NOW,
    })
    print("   ✅ CREDIT  (is_credit=True)")
    print("   ✅ REWARD_REDEMPTION  (is_credit=False)\n")


# ─────────────────────────────────────────────────────────────────────────────
# ROLES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_roles():
    print("👥 Seeding roles...")
    roles = [
        ("SUPER_ADMIN", "Super Admin", "Full system access",     "1.5000"),
        ("HR_ADMIN",    "HR Admin",    "Employee management",    "1.2000"),
        ("MANAGER",     "Manager",     "Team management",        "1.3000"),
        ("EMPLOYEE",    "Employee",    "Self-service access",    "1.0000"),
        ("AUDITOR",     "Auditor",     "Audit read-only access", "1.0000"),
    ]
    for code, name, desc, weight in roles:
        await db.roles.create(data={
            "role_name":       name,
            "role_code":       code,
            "description":     desc,
            "reviewer_weight": weight,
            "updated_at":      NOW,
        })
        print(f"   ✅ {code:15s}  reviewer_weight={weight}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENT TYPES & DEPARTMENTS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_departments():
    print("🏢 Seeding department_types & departments...")
    for type_id, name, code in [
        (TECH_TYPE_ID, "Technology", "TECH"),
        (MGMT_TYPE_ID, "Management", "MGMT"),
    ]:
        await db.department_types.create(data={
            "department_type_id": type_id,
            "type_name":          name,
            "type_code":          code,
            "updated_at":         NOW,
        })
    for dept_id, name, code, type_id in [
        (ENG_DEPT_ID, "Engineering",     "ENG", TECH_TYPE_ID),
        (HR_DEPT_ID,  "Human Resources", "HR",  MGMT_TYPE_ID),
    ]:
        await db.departments.create(data={
            "department_id":      dept_id,
            "department_name":    name,
            "department_code":    code,
            "department_type_id": type_id,
            "updated_at":         NOW,
        })
    print("   ✅ TECH, MGMT (department_types)")
    print("   ✅ ENG, HR (departments)\n")


# ─────────────────────────────────────────────────────────────────────────────
# DESIGNATIONS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_designations():
    print("🎖️  Seeding designations...")
    for desig_id, name, code, level in [
        (ADMIN_DESIG_ID,  "System Administrator", "SYS_ADMIN", 0),
        (MGR_DESIG_ID,    "Engineering Manager",  "ENG_MGR",   2),
        (SR_DEV_DESIG_ID, "Senior Developer",     "SR_DEV",    3),
    ]:
        await db.designations.create(data={
            "designation_id":   desig_id,
            "designation_name": name,
            "designation_code": code,
            "level":            level,
            "updated_at":       NOW,
        })
        print(f"   ✅ {code:12s}  level={level}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# POINTS CONFIG
# ─────────────────────────────────────────────────────────────────────────────
async def seed_points_config():
    print("⚙️  Seeding points_config...")
    configs = [
        (PC_BASE_ID, "BASE_POINTS_PER_STAR",  "2.200000", "Base points awarded per star in a review rating",           date(2024, 1, 1)),
        (PC_MAX_ID,  "MAX_POINTS_PER_REVIEW", "50.000000", "Maximum points that can be awarded from a single review",  date(2024, 1, 1)),
    ]
    for config_id, key, value, desc, eff_from in configs:
        await db.points_config.create(data={
            "config_id":      config_id,
            "config_key":     key,
            "config_value":   value,
            "description":    desc,
            "effective_from": datetime.combine(eff_from, datetime.min.time()),
            "created_by":     ADMIN_ID,
            "updated_by":     ADMIN_ID,
            "updated_at":     NOW,
        })
        print(f"   ✅ {key}  = {value}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_review_categories():
    print("🏷️  Seeding review_categories...")
    cats = [
        (RC_OWNERSHIP_ID,  "OWNERSHIP",     "Ownership",     "1.2000", "Taking responsibility and driving results"),
        (RC_INNOVATION_ID, "INNOVATION",    "Innovation",    "1.3000", "Creative thinking and problem solving"),
        (RC_COLLAB_ID,     "COLLABORATION", "Collaboration", "1.1000", "Teamwork and cross-functional cooperation"),
        (RC_LEADERSHIP_ID, "LEADERSHIP",    "Leadership",    "1.4000", "Inspiring and guiding others"),
    ]
    for cat_id, code, name, multiplier, desc in cats:
        await db.review_categories.create(data={
            "category_id":   cat_id,
            "category_code": code,
            "category_name": name,
            "multiplier":    multiplier,
            "description":   desc,
            "is_active":     True,
            "created_by":    ADMIN_ID,
            "updated_by":    ADMIN_ID,
            "updated_at":    NOW,
        })
        print(f"   ✅ {code:15s}  multiplier={multiplier}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# SEASONAL MULTIPLIERS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_seasonal_multipliers():
    print("📅 Seeding seasonal_multipliers...")
    quarters = [
        (SM_Q1_ID, 1, "Q1 Standard", "1.0000", date(2025, 1,  1), date(2025,  3, 31)),
        (SM_Q2_ID, 2, "Q2 Standard", "1.0000", date(2025, 4,  1), date(2025,  6, 30)),
        (SM_Q3_ID, 3, "Q3 Mid-Year", "1.1000", date(2025, 7,  1), date(2025,  9, 30)),
        (SM_Q4_ID, 4, "Q4 Year-End", "1.2500", date(2025, 10, 1), date(2025, 12, 31)),
    ]
    for sm_id, quarter, label, multiplier, eff_from, eff_to in quarters:
        await db.seasonal_multipliers.create(data={
            "seasonal_multiplier_id": sm_id,
            "quarter":                quarter,
            "label":                  label,
            "multiplier":             multiplier,
            "effective_from":         datetime.combine(eff_from, datetime.min.time()),
            "effective_to":           datetime.combine(eff_to,   datetime.min.time()),
            "created_by":             ADMIN_ID,
            "updated_by":             ADMIN_ID,
            "updated_at":             NOW,
        })
        print(f"   ✅ {label:18s}  x{multiplier}  ({eff_from} → {eff_to})")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEES — admin bootstrap
# ─────────────────────────────────────────────────────────────────────────────
async def seed_employees_admin_only():
    print("👤 Seeding admin employee (bootstrap)...")
    hashed = hash_password(TEST_PASSWORD)

    await db.employees.create(data={
        "employee_id":     ADMIN_ID,
        "username":        "admin.user",
        "email":           "admin@company.com",
        "password_hash":   hashed,
        "designation_id":  ADMIN_DESIG_ID,
        "department_id":   HR_DEPT_ID,
        "status_id":       ACTIVE_STATUS_ID,
        "date_of_joining": datetime.combine(date(2020, 1, 1), datetime.min.time()),
        "date_of_birth":   datetime.combine(TODAY, datetime.min.time()),  # 🎂 today
        "created_by":      ADMIN_ID,
        "updated_by":      ADMIN_ID,
        "updated_at":      NOW,
    })
    await db.wallets.create(data={
        "employee_id":         ADMIN_ID,
        "available_points":    999999,
        "redeemed_points":     0,
        "total_earned_points": 999999,
        "version":             1,
        "created_by":          ADMIN_ID,
        "updated_by":          ADMIN_ID,
        "updated_at":          NOW,
    })
    print(f"   ✅ admin.user  (dob={TODAY}  🎂 birthday today!)\n")


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEES — rest (jane, john + 3 new users)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_employees_rest():
    print("👤 Seeding remaining employees...")
    print(f"   🔑 Password for ALL accounts: {TEST_PASSWORD}\n")
    hashed = hash_password(TEST_PASSWORD)

    employees = [
        # (id, username, email, desig_id, dept_id, manager_id, doj, avail_pts, redeemed, total, version)
        (JANE_ID,      "jane.smith",           "jane.smith@company.com",          MGR_DESIG_ID,    ENG_DEPT_ID, None,    date(2022, 1,  1), 5000, 0,   5000, 1),
        (JOHN_ID,      "john.doe",             "john.doe@company.com",            SR_DEV_DESIG_ID, ENG_DEPT_ID, JANE_ID, date(2024, 1, 15), 1500, 500, 2000, 5),
        (ARIJIT_ID,    "arijit.banik",         "arijitb017@gmail.com",            SR_DEV_DESIG_ID, ENG_DEPT_ID, JANE_ID, date(2024, 3,  1), 0,    0,   0,    1),
        (SHUBRAJIT_ID, "shubrajit.deb",        "shubrajitdeb180603@gmail.com",    SR_DEV_DESIG_ID, ENG_DEPT_ID, JANE_ID, date(2024, 3,  1), 0,    0,   0,    1),
        (PRASUN_ID,    "prasun.chakraborty",   "nothingshere21@gmail.com",        SR_DEV_DESIG_ID, ENG_DEPT_ID, JANE_ID, date(2024, 3,  1), 0,    0,   0,    1),
    ]

    for (emp_id, username, email, desig_id, dept_id, manager_id,
         doj, avail_pts, redeemed_pts, total_pts, version) in employees:
        await db.employees.create(data={
            "employee_id":     emp_id,
            "username":        username,
            "email":           email,
            "password_hash":   hashed,
            "designation_id":  desig_id,
            "department_id":   dept_id,
            **({"manager_id": manager_id} if manager_id else {}),
            "status_id":       ACTIVE_STATUS_ID,
            "date_of_joining": datetime.combine(doj, datetime.min.time()),
            "date_of_birth":   datetime.combine(TODAY, datetime.min.time()),  # 🎂 today
            "created_by":      ADMIN_ID,
            "updated_by":      ADMIN_ID,
            "updated_at":      NOW,
        })
        await db.wallets.create(data={
            "employee_id":         emp_id,
            "available_points":    avail_pts,
            "redeemed_points":     redeemed_pts,
            "total_earned_points": total_pts,
            "version":             version,
            "created_by":          ADMIN_ID,
            "updated_by":          ADMIN_ID,
            "updated_at":          NOW,
        })
        print(f"   ✅ {username:25s}  dob={TODAY}  🎂  wallet: {avail_pts} pts")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEE ROLES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_employee_roles():
    print("🔐 Assigning employee roles...")
    roles = await db.roles.find_many()
    role_map = {r.role_code: r.role_id for r in roles}

    name_map = {
        ADMIN_ID:     "admin.user",
        JANE_ID:      "jane.smith",
        JOHN_ID:      "john.doe",
        ARIJIT_ID:    "arijit.banik",
        SHUBRAJIT_ID: "shubrajit.deb",
        PRASUN_ID:    "prasun.chakraborty",
    }

    assignments = [
        (ADMIN_ID,      "SUPER_ADMIN"),
        (ADMIN_ID,      "HR_ADMIN"),
        (JANE_ID,       "MANAGER"),
        (JANE_ID,       "EMPLOYEE"),
        (JOHN_ID,       "EMPLOYEE"),
        (ARIJIT_ID,     "EMPLOYEE"),
        (SHUBRAJIT_ID,  "EMPLOYEE"),
        (PRASUN_ID,     "EMPLOYEE"),
    ]

    for emp_id, role_code in assignments:
        await db.employee_roles.create(data={
            "employee_id": emp_id,
            "role_id":     role_map[role_code],
            "assigned_by": ADMIN_ID,
            "is_active":   True,
            "created_by":  ADMIN_ID,
            "updated_by":  ADMIN_ID,
            "updated_at":  NOW,
        })
        print(f"   ✅ {name_map[emp_id]:25s} → {role_code}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# REWARD CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reward_categories():
    print("🏷️  Seeding reward_categories...")
    cats = [
        (GIFT_CARD_CAT_ID,   "Gift Cards",  "GIFT_CARD",   "Digital and physical gift cards"),
        (MERCHANDISE_CAT_ID, "Merchandise", "MERCHANDISE", "Company branded merchandise and physical items"),
        (EXPERIENCE_CAT_ID,  "Experiences", "EXPERIENCE",  "Events, courses, and experiences"),
    ]
    for cat_id, name, code, desc in cats:
        await db.reward_categories.create(data={
            "category_id":   cat_id,
            "category_name": name,
            "category_code": code,
            "description":   desc,
            "is_active":     True,
            "created_by":    ADMIN_ID,
            "updated_by":    ADMIN_ID,
            "updated_at":    NOW,
        })
        print(f"   ✅ {code}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# REWARD CATALOG
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reward_catalog():
    print("🎁 Seeding reward_catalog...")
    items = [
        ("Amazon Gift Card $10",  "REW-AMZ-10",       "Amazon digital gift card worth $10",           GIFT_CARD_CAT_ID,   100, 100, 100,  50),
        ("Amazon Gift Card $25",  "REW-AMZ-25",       "Amazon digital gift card worth $25",           GIFT_CARD_CAT_ID,   250, 250, 250,  30),
        ("Company T-Shirt",       "REW-MERCH-SHIRT",  "Premium company branded T-shirt",              MERCHANDISE_CAT_ID, 200, 200, 200, 100),
        ("Company Hoodie",        "REW-MERCH-HOODIE", "Premium company branded hoodie",               MERCHANDISE_CAT_ID, 400, 400, 400,  40),
        ("Udemy Course Voucher",  "REW-LEARN-UDEMY",  "One Udemy course of your choice",              EXPERIENCE_CAT_ID,  300, 300, 300,  20),
        ("Team Lunch Voucher",    "REW-EXP-LUNCH",    "Lunch for you and your team (up to 5 people)", EXPERIENCE_CAT_ID,  500, 500, 500,  15),
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
            "category_id":    cat_id,
            "created_by":     ADMIN_ID,
            "updated_by":     ADMIN_ID,
            "updated_at":     NOW,
        })
        await db.execute_raw(
            f"UPDATE reward_catalog SET available_stock = {stock} "
            f"WHERE catalog_id = '{item.catalog_id}'"
        )
        print(f"   ✅ {code:25s}  {default_pts} pts  stock: {stock}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS  (jane reviews john)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reviews():
    print("⭐ Seeding reviews + review_category_tags...")
    review_id = uid()
    await db.reviews.create(data={
        "review_id":   review_id,
        "reviewer_id": JANE_ID,
        "receiver_id": JOHN_ID,
        "rating":      4,
        "comment":     "John delivered the new auth module on time with excellent test coverage.",
        "status_id":   REVIEW_ACTIVE_ID,
        "raw_points":  17.6,
        "created_by":  JANE_ID,
        "updated_by":  JANE_ID,
        "updated_at":  NOW,
    })
    for cat_id, mult, code in [
        (RC_OWNERSHIP_ID, "1.2000", "OWNERSHIP"),
        (RC_COLLAB_ID,    "1.1000", "COLLABORATION"),
    ]:
        await db.review_category_tags.create(data={
            "review_id":              review_id,
            "category_id":            cat_id,
            "multiplier_snapshot":    mult,
            "category_code_snapshot": code,
        })
    print(f"   ✅ jane.smith → john.doe  rating=4  raw_points=17.6")
    print(f"   ✅ Tags: OWNERSHIP (x1.2), COLLABORATION (x1.1)\n")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_transactions():
    print("💰 Seeding transactions...")
    john_wallet = await db.wallets.find_unique(where={"employee_id": JOHN_ID})
    txn_data = [
        (200, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Points from Q1 performance review", "TXN-REF-001", -30),
        (300, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Points from Q2 performance review", "TXN-REF-002", -10),
        (500, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Company Hoodie", "TXN-REF-003",  -5),
    ]
    for amount, type_id, status_id, desc, ref, offset in txn_data:
        await db.transactions.create(data={
            "wallet_id":           john_wallet.wallet_id,
            "amount":              amount,
            "transaction_type_id": type_id,
            "status_id":           status_id,
            "description":         desc,
            "reference_number":    ref,
            "transaction_at":      NOW + timedelta(days=offset),
            "created_by":          JOHN_ID,
            "updated_by":          JOHN_ID,
            "updated_at":          NOW,
        })
        sign = "+" if type_id == CREDIT_TYPE_ID else "-"
        print(f"   ✅ {ref}  {sign}{amount} pts  {desc}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# REWARD HISTORY
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reward_history():
    print("🎀 Seeding reward_history...")
    john_wallet = await db.wallets.find_unique(where={"employee_id": JOHN_ID})
    hoodie = await db.reward_catalog.find_unique(where={"reward_code": "REW-MERCH-HOODIE"})
    await db.reward_history.create(data={
        "wallet_id":  john_wallet.wallet_id,
        "catalog_id": hoodie.catalog_id,
        "granted_by": ADMIN_ID,
        "points":     400,
        "comment":    "Redeemed as end-of-year reward",
        "granted_at": NOW + timedelta(days=-5),
        "created_by": JOHN_ID,
        "updated_by": JOHN_ID,
        "updated_at": NOW,
    })
    print("   ✅ john.doe redeemed Company Hoodie (400 pts)\n")


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────────
async def seed_audit_log():
    print("📝 Seeding audit_log...")
    import json
    entries = [
        ("employees", JOHN_ID, "INSERT", None,                       {"username": "john.doe", "status": "ACTIVE"},              ADMIN_ID),
        ("wallets",   JOHN_ID, "UPDATE", {"available_points": 1700}, {"available_points": 1500},                                ADMIN_ID),
        ("reviews",   uid(),   "INSERT", None,                       {"reviewer": "jane.smith", "receiver": "john.doe", "rating": 4}, JANE_ID),
    ]
    for table, record_id, operation, old_vals, new_vals, performer in entries:
        old_sql = f"'{json.dumps(old_vals)}'::jsonb" if old_vals else "NULL"
        new_sql = f"'{json.dumps(new_vals)}'::jsonb"
        await db.execute_raw(f"""
            INSERT INTO audit_log
                (audit_id, table_name, record_id, operation_type,
                 old_values, new_values, performed_by,
                 ip_address, user_agent, performed_at)
            VALUES (
                '{uid()}', '{table}', '{record_id}', '{operation}',
                {old_sql}, {new_sql}, '{performer}',
                '127.0.0.1', 'seed-script/1.0', NOW()
            )
        """)
        print(f"   ✅ {operation:6s}  {table}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# BACKFILL
# ─────────────────────────────────────────────────────────────────────────────
async def backfill_audit_fields():
    print("🔧 Backfilling created_by / updated_by on early tables...")
    for table in ["department_types", "departments", "designations"]:
        await db.execute_raw(
            f"UPDATE {table} "
            f"SET created_by = '{ADMIN_ID}', updated_by = '{ADMIN_ID}' "
            f"WHERE created_by IS NULL"
        )
        print(f"   ✅ {table}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    await db.connect()
    try:
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
        await seed_employees_admin_only()
        await seed_employees_rest()
        await backfill_audit_fields()
        await seed_points_config()
        await seed_review_categories()
        await seed_seasonal_multipliers()
        await seed_employee_roles()
        await seed_reward_categories()
        await seed_reward_catalog()
        await seed_reviews()
        await seed_transactions()
        await seed_reward_history()
        await seed_audit_log()

        print("=" * 65)
        print("🎉  SEED COMPLETE!")
        print("=" * 65)
        print()
        print("📝 Login credentials (all share the same password):")
        print()
        print("   username: admin.user            roles: SUPER_ADMIN, HR_ADMIN")
        print("   username: jane.smith            roles: MANAGER, EMPLOYEE")
        print("   username: john.doe              role:  EMPLOYEE")
        print("   username: arijit.banik          role:  EMPLOYEE  | arijitb017@gmail.com")
        print("   username: shubrajit.deb         role:  EMPLOYEE  | shubrajitdeb180603@gmail.com")
        print("   username: prasun.chakraborty    role:  EMPLOYEE  | nothingshere21@gmail.com")
        print()
        print(f"   password (all): {TEST_PASSWORD}")
        print()
        print(f"   🎂 All DOBs = {TODAY} (today) → birthday notifications will fire!")
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