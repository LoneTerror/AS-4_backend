"""
Complete database seeding script for Employee Rewards System.
Self-contained — seeds everything from scratch in the correct order.

Run with:
    python seed.py

Formula: raw_points = sum(category_multipliers) × reviewer_weight
  reviewer_weight comes from roles table:
    SUPER_ADMIN=1.5, HR_ADMIN=1.2, MANAGER=1.3, EMPLOYEE=1.0

Review categories (positive only):
  OWNERSHIP     multiplier=1.2
  INNOVATION    multiplier=1.3
  COLLABORATION multiplier=1.1
  LEADERSHIP    multiplier=1.4

What's seeded:
    status_master          — 7 statuses
    transaction_types      — CREDIT, REWARD_REDEMPTION
    roles                  — SUPER_ADMIN, HR_ADMIN, MANAGER, EMPLOYEE, AUDITOR
    department_types       — TECH, MGMT, FINANCE, OPERATIONS
    departments            — ENG, HR, FINANCE, OPS, QA, DEVOPS
    designations           — 9 designations
    review_categories      — 4 positive only
    seasonal_multipliers   — Q1–Q4 2025 (kept in DB, not used in points formula)
    employees              — 17 employees
    wallets                — 1 per employee
    employee_roles         — role assignments
    reward_categories      — GIFT_CARD, MERCHANDISE, EXPERIENCE, WELLNESS
    reward_catalog         — 12 items
    reviews                — 15 reviews (no rating column)
    review_category_tags   — 2 tags per review
    transactions           — 31 transactions
    reward_history         — 10 redemptions
    notifications          — 15 notifications
    audit_log              — 15 entries
"""
import os
import json
import uuid
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

import asyncio
from datetime import date, datetime, timezone, timedelta

from src.prisma.client import db
from src.core.security import hash_password

TEST_PASSWORD = "Password123!"
TODAY         = date.today()
NOW           = datetime.now(timezone.utc)

def uid() -> str:
    return str(uuid.uuid4())

def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)

# ── Fixed IDs ─────────────────────────────────────────────────────────────────
ADMIN_ID      = "110e8400-e29b-41d4-a716-446655440000"
JANE_ID       = "880e8400-e29b-41d4-a716-446655440000"
JOHN_ID       = "550e8400-e29b-41d4-a716-446655440000"
ARIJIT_ID     = "aa1e8400-e29b-41d4-a716-446655440001"
SHUBRAJIT_ID  = "bb1e8400-e29b-41d4-a716-446655440002"
PRASUN_ID     = "cc1e8400-e29b-41d4-a716-446655440003"
MIDANKA_ID    = "dd1e8400-e29b-41d4-a716-446655440004"
SWARUP_ID     = "ee1e8400-e29b-41d4-a716-446655440005"
BIKASH_N_ID   = "ff1e8400-e29b-41d4-a716-446655440006"
BINIT_ID      = "aa2e8400-e29b-41d4-a716-446655440007"
MRINMOY_ID    = "bb2e8400-e29b-41d4-a716-446655440008"
ROHIT_ID      = "cc2e8400-e29b-41d4-a716-446655440009"
RISHAV_ID     = "dd2e8400-e29b-41d4-a716-446655440010"
AMINUL_ID     = "ee2e8400-e29b-41d4-a716-446655440011"
BIKASH_B_ID   = "ff2e8400-e29b-41d4-a716-446655440012"
DIPAM_ID      = "aa3e8400-e29b-41d4-a716-446655440013"
GAUTAM_ID     = "bb3e8400-e29b-41d4-a716-446655440014"

ACTIVE_STATUS_ID   = "990e8400-e29b-41d4-a716-446655440000"
INACTIVE_STATUS_ID = "990e8400-e29b-41d4-a716-446655440001"
TXN_PENDING_ID     = "990e8400-e29b-41d4-a716-446655440002"
TXN_APPROVED_ID    = "990e8400-e29b-41d4-a716-446655440003"
TXN_REJECTED_ID    = "990e8400-e29b-41d4-a716-446655440004"
REVIEW_ACTIVE_ID   = "990e8400-e29b-41d4-a716-446655440005"
REVIEW_DELETED_ID  = "990e8400-e29b-41d4-a716-446655440006"

TECH_TYPE_ID    = "aa0e8400-e29b-41d4-a716-446655440001"
MGMT_TYPE_ID    = "aa0e8400-e29b-41d4-a716-446655440002"
FINANCE_TYPE_ID = "aa0e8400-e29b-41d4-a716-446655440003"
OPS_TYPE_ID     = "aa0e8400-e29b-41d4-a716-446655440004"

ENG_DEPT_ID     = "770e8400-e29b-41d4-a716-446655440000"
HR_DEPT_ID      = "330e8400-e29b-41d4-a716-446655440000"
FINANCE_DEPT_ID = "440e8400-e29b-41d4-a716-446655440000"
OPS_DEPT_ID     = "551e8400-e29b-41d4-a716-446655440000"
QA_DEPT_ID      = "660e8400-e29b-41d4-a716-446655441000"
DEVOPS_DEPT_ID  = "771e8400-e29b-41d4-a716-446655441001"

ADMIN_DESIG_ID     = "660e8400-e29b-41d4-a716-446655440002"
MGR_DESIG_ID       = "660e8400-e29b-41d4-a716-446655440001"
SR_DEV_DESIG_ID    = "660e8400-e29b-41d4-a716-446655440000"
TEAM_LEAD_DESIG_ID = "660e8400-e29b-41d4-a716-446655440003"
JR_DEV_DESIG_ID    = "660e8400-e29b-41d4-a716-446655440004"
QA_LEAD_DESIG_ID   = "660e8400-e29b-41d4-a716-446655440005"
DEVOPS_DESIG_ID    = "660e8400-e29b-41d4-a716-446655440006"
HR_MGR_DESIG_ID    = "660e8400-e29b-41d4-a716-446655440007"
FIN_ANA_DESIG_ID   = "660e8400-e29b-41d4-a716-446655440008"

CREDIT_TYPE_ID            = "bb0e8400-e29b-41d4-a716-446655440001"
REWARD_REDEMPTION_TYPE_ID = "bb0e8400-e29b-41d4-a716-446655440002"

GIFT_CARD_CAT_ID   = "cc0e8400-e29b-41d4-a716-446655440001"
MERCHANDISE_CAT_ID = "cc0e8400-e29b-41d4-a716-446655440002"
EXPERIENCE_CAT_ID  = "cc0e8400-e29b-41d4-a716-446655440003"
WELLNESS_CAT_ID    = "cc0e8400-e29b-41d4-a716-446655440004"

# ── Review categories (positive only) ────────────────────────────────────────
RC_OWNERSHIP_ID  = "dd0e8400-e29b-41d4-a716-446655440001"
RC_INNOVATION_ID = "dd0e8400-e29b-41d4-a716-446655440002"
RC_COLLAB_ID     = "dd0e8400-e29b-41d4-a716-446655440003"
RC_LEADERSHIP_ID = "dd0e8400-e29b-41d4-a716-446655440004"

# multipliers as floats for raw_points calculation
M_OWNERSHIP  = 1.2
M_INNOVATION = 1.3
M_COLLAB     = 1.1
M_LEADERSHIP = 1.4

# reviewer_weight by role
W_SUPER_ADMIN = 1.5
W_HR_ADMIN    = 1.2
W_MANAGER     = 1.3
W_EMPLOYEE    = 1.0

SM_Q1_ID = "ff0e8400-e29b-41d4-a716-446655440001"
SM_Q2_ID = "ff0e8400-e29b-41d4-a716-446655440002"
SM_Q3_ID = "ff0e8400-e29b-41d4-a716-446655440003"
SM_Q4_ID = "ff0e8400-e29b-41d4-a716-446655440004"

def pts(multipliers: list, weight: float) -> float:
    """raw_points = sum(category_multipliers) × reviewer_weight"""
    return round(sum(multipliers) * weight, 4)


# ─────────────────────────────────────────────────────────────────────────────
async def clean_db():
    print("🧹 Cleaning existing data...")
    try:
        await db.execute_raw("""
            TRUNCATE TABLE
                audit_log, review_category_tags, reviews, transactions,
                reward_history, refresh_tokens, employee_roles, wallets,
                notifications, employees, reward_catalog, reward_categories,
                transaction_types, review_categories,
                designations, departments, department_types,
                route_permissions, roles, status_master
            CASCADE
        """)
        print("   ✓ CASCADE truncate successful\n")
    except Exception as e:
        print(f"   ⚠ CASCADE truncate failed: {e}")
        for name, table in [
            ("audit_log", db.audit_log), ("review_category_tags", db.review_category_tags),
            ("reviews", db.reviews), ("transactions", db.transactions),
            ("reward_history", db.reward_history), ("refresh_tokens", db.refresh_tokens),
            ("employee_roles", db.employee_roles), ("wallets", db.wallets),
            ("employees", db.employees), ("reward_catalog", db.reward_catalog),
            ("reward_categories", db.reward_categories), ("transaction_types", db.transaction_types),
            ("review_categories", db.review_categories), ("seasonal_multipliers", db.seasonal_multipliers),
            ("designations", db.designations), ("departments", db.departments),
            ("department_types", db.department_types), ("roles", db.roles),
            ("status_master", db.status_master),
        ]:
            try:
                count = await table.delete_many()
                if count: print(f"   ✓ Deleted {count} {name} rows")
            except Exception as ex:
                print(f"   ✗ Could not delete {name}: {ex}")
        print()


async def seed_status_master():
    print("📋 Seeding status_master...")
    rows = [
        (ACTIVE_STATUS_ID,   "ACTIVE",         "Active",   "GENERAL",     "Entity is active"),
        (INACTIVE_STATUS_ID, "INACTIVE",       "Inactive", "GENERAL",     "Entity is inactive"),
        (TXN_PENDING_ID,     "PENDING",        "Pending",  "TRANSACTION", "Transaction is pending approval"),
        (TXN_APPROVED_ID,    "APPROVED",       "Approved", "TRANSACTION", "Transaction has been approved"),
        (TXN_REJECTED_ID,    "REJECTED",       "Rejected", "TRANSACTION", "Transaction has been rejected"),
        (REVIEW_ACTIVE_ID,   "REVIEW_ACTIVE",  "Active",   "REVIEW",      "Review is active and visible"),
        (REVIEW_DELETED_ID,  "REVIEW_DELETED", "Deleted",  "REVIEW",      "Review has been soft-deleted"),
    ]
    for status_id, code, name, entity, desc in rows:
        await db.status_master.create(data={
            "status_id": status_id, "status_code": code, "status_name": name,
            "entity_type": entity, "description": desc, "updated_at": NOW,
        })
    print("   ✅ GENERAL: ACTIVE, INACTIVE")
    print("   ✅ TRANSACTION: PENDING, APPROVED, REJECTED")
    print("   ✅ REVIEW: REVIEW_ACTIVE, REVIEW_DELETED\n")


async def seed_transaction_types():
    print("💳 Seeding transaction_types...")
    await db.transaction_types.create(data={
        "type_id": CREDIT_TYPE_ID, "type_name": "Credit", "type_code": "CREDIT",
        "description": "Points credited to wallet from a performance review",
        "is_credit": True, "updated_at": NOW,
    })
    await db.transaction_types.create(data={
        "type_id": REWARD_REDEMPTION_TYPE_ID, "type_name": "Reward Redemption",
        "type_code": "REWARD_REDEMPTION",
        "description": "Points deducted when an employee redeems a reward",
        "is_credit": False, "updated_at": NOW,
    })
    print("   ✅ CREDIT, REWARD_REDEMPTION\n")


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
            "role_name": name, "role_code": code, "description": desc,
            "reviewer_weight": weight, "updated_at": NOW,
        })
        print(f"   ✅ {code:15s}  reviewer_weight={weight}")
    print()


async def seed_departments():
    print("🏢 Seeding department_types & departments...")
    for type_id, name, code in [
        (TECH_TYPE_ID, "Technology", "TECH"), (MGMT_TYPE_ID, "Management", "MGMT"),
        (FINANCE_TYPE_ID, "Finance", "FINANCE"), (OPS_TYPE_ID, "Operations", "OPS"),
    ]:
        await db.department_types.create(data={
            "department_type_id": type_id, "type_name": name, "type_code": code, "updated_at": NOW,
        })
    for dept_id, name, code, type_id in [
        (ENG_DEPT_ID, "Engineering", "ENG", TECH_TYPE_ID),
        (HR_DEPT_ID, "Human Resources", "HR", MGMT_TYPE_ID),
        (FINANCE_DEPT_ID, "Finance", "FIN", FINANCE_TYPE_ID),
        (OPS_DEPT_ID, "Operations", "OPS", OPS_TYPE_ID),
        (QA_DEPT_ID, "Quality Assurance", "QA", TECH_TYPE_ID),
        (DEVOPS_DEPT_ID, "DevOps", "DEVOPS", TECH_TYPE_ID),
    ]:
        await db.departments.create(data={
            "department_id": dept_id, "department_name": name, "department_code": code,
            "department_type_id": type_id, "updated_at": NOW,
        })
    print("   ✅ department_types: TECH, MGMT, FINANCE, OPS")
    print("   ✅ departments: ENG, HR, FINANCE, OPS, QA, DEVOPS\n")


async def seed_designations():
    print("🎖️  Seeding designations...")
    for desig_id, name, code, level, desc in [
        (ADMIN_DESIG_ID,     "System Administrator", "SYS_ADMIN",   0, "Top-level system administrator"),
        (MGR_DESIG_ID,       "Engineering Manager",  "ENG_MGR",     2, "Manages engineering teams"),
        (TEAM_LEAD_DESIG_ID, "Team Lead",            "TEAM_LEAD",   2, "Leads a squad of engineers"),
        (SR_DEV_DESIG_ID,    "Senior Developer",     "SR_DEV",      3, "Senior individual contributor"),
        (JR_DEV_DESIG_ID,    "Junior Developer",     "JR_DEV",      4, "Entry-level software developer"),
        (QA_LEAD_DESIG_ID,   "QA Lead",              "QA_LEAD",     3, "Leads quality assurance processes"),
        (DEVOPS_DESIG_ID,    "DevOps Engineer",      "DEVOPS_ENG",  3, "Manages CI/CD pipelines"),
        (HR_MGR_DESIG_ID,    "HR Manager",           "HR_MGR",      2, "Manages HR operations"),
        (FIN_ANA_DESIG_ID,   "Finance Analyst",      "FIN_ANALYST", 3, "Handles financial analysis"),
    ]:
        await db.designations.create(data={
            "designation_id": desig_id, "designation_name": name, "designation_code": code,
            "level": level, "description": desc, "is_active": True, "updated_at": NOW,
        })
        print(f"   ✅ {code:15s}  level={level}")
    print()


async def seed_review_categories():
    print("🏷️  Seeding review_categories (positive only)...")
    for cat_id, code, name, multiplier, desc in [
        (RC_OWNERSHIP_ID,  "OWNERSHIP",     "Ownership",     "1.2000", "Taking responsibility and driving results"),
        (RC_INNOVATION_ID, "INNOVATION",    "Innovation",    "1.3000", "Creative thinking and problem solving"),
        (RC_COLLAB_ID,     "COLLABORATION", "Collaboration", "1.1000", "Teamwork and cross-functional cooperation"),
        (RC_LEADERSHIP_ID, "LEADERSHIP",    "Leadership",    "1.4000", "Inspiring and guiding others"),
    ]:
        await db.review_categories.create(data={
            "category_id": cat_id, "category_code": code, "category_name": name,
            "multiplier": multiplier, "description": desc, "is_active": True,
            "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
        })
        print(f"   ✅ {code:15s}  ×{multiplier}")
    print()


async def seed_employees_admin_only():
    print("👤 Seeding admin employee (bootstrap)...")
    hashed = hash_password(TEST_PASSWORD)
    await db.employees.create(data={
        "employee_id": ADMIN_ID, "username": "admin.user", "email": "admin@company.com",
        "password_hash": hashed, "designation_id": ADMIN_DESIG_ID, "department_id": HR_DEPT_ID,
        "status_id": ACTIVE_STATUS_ID,
        "date_of_joining": datetime.combine(date(2020, 1, 1), datetime.min.time()),
        "date_of_birth":   datetime.combine(TODAY, datetime.min.time()),
        "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
    })
    await db.wallets.create(data={
        "employee_id": ADMIN_ID, "available_points": 999999, "redeemed_points": 0,
        "total_earned_points": 999999, "version": 1,
        "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
    })
    print(f"   ✅ admin.user\n")


async def seed_employees_rest():
    print("👤 Seeding all team employees...")
    print(f"   🔑 Password for ALL accounts: {TEST_PASSWORD}\n")
    hashed = hash_password(TEST_PASSWORD)

    # id, username, email, desig, dept, manager, dob, doj, avail, redeemed, total, version
    employees = [
        (JANE_ID,      "jane.smith",         "jane.smith@company.com",         MGR_DESIG_ID,       ENG_DEPT_ID,    None,       date(1990,5,10),  date(2022,1,1),  5200,400,5600,8),
        (JOHN_ID,      "john.doe",           "john.doe@company.com",           SR_DEV_DESIG_ID,    ENG_DEPT_ID,    JANE_ID,    date(1995,8,15),  date(2024,1,15), 1800,500,2300,6),
        (ARIJIT_ID,    "arijit.banik",       "arijitb017@gmail.com",           SR_DEV_DESIG_ID,    ENG_DEPT_ID,    JANE_ID,    date(2000,3,17),  date(2024,3,1),  2400,200,2600,4),
        (SHUBRAJIT_ID, "shubrajit.deb",      "shubrajitdeb180603@gmail.com",   SR_DEV_DESIG_ID,    ENG_DEPT_ID,    JANE_ID,    date(2003,6,18),  date(2024,3,1),  2100,0,  2100,3),
        (PRASUN_ID,    "prasun.chakraborty", "nothingshere21@gmail.com",       TEAM_LEAD_DESIG_ID, ENG_DEPT_ID,    JANE_ID,    date(1998,11,25), date(2024,3,1),  3100,300,3400,5),
        (MIDANKA_ID,   "midanka.lahon",      "midankalahon@gmail.com",         JR_DEV_DESIG_ID,    ENG_DEPT_ID,    PRASUN_ID,  date(2001,7,14),  date(2024,6,1),   950,0,   950,2),
        (SWARUP_ID,    "swarup.das",         "swarup1to3@gmail.com",           SR_DEV_DESIG_ID,    DEVOPS_DEPT_ID, JANE_ID,    date(1997,2,22),  date(2023,8,15), 2750,250,3000,5),
        (BIKASH_N_ID,  "bikash.nath",        "nathbikash231@gmail.com",        DEVOPS_DESIG_ID,    DEVOPS_DEPT_ID, SWARUP_ID,  date(1999,4,5),   date(2024,2,1),  1600,100,1700,3),
        (BINIT_ID,     "binit.goswami",      "binitkgsmile2005@gmail.com",     JR_DEV_DESIG_ID,    ENG_DEPT_ID,    PRASUN_ID,  date(2005,1,10),  date(2024,7,1),   700,0,   700,2),
        (MRINMOY_ID,   "mrinmoy.kashyap",    "mrinmoykashyap.mk@gmail.com",    QA_LEAD_DESIG_ID,   QA_DEPT_ID,     JANE_ID,    date(1996,9,30),  date(2023,5,10), 2900,400,3300,6),
        (ROHIT_ID,     "rohit.sah",          "rsah94614@gmail.com",            JR_DEV_DESIG_ID,    ENG_DEPT_ID,    PRASUN_ID,  date(2002,12,3),  date(2024,9,1),   500,0,   500,1),
        (RISHAV_ID,    "rishav.bora",        "rishavbora550@gmail.com",        SR_DEV_DESIG_ID,    QA_DEPT_ID,     MRINMOY_ID, date(1998,3,19),  date(2023,11,1), 2200,200,2400,4),
        (AMINUL_ID,    "aminul.islam",       "animul7535@gmail.com",           JR_DEV_DESIG_ID,    ENG_DEPT_ID,    PRASUN_ID,  date(2003,5,27),  date(2025,1,15),  300,0,   300,1),
        (BIKASH_B_ID,  "bikash.bora",        "borab796@gmail.com",             DEVOPS_DESIG_ID,    DEVOPS_DEPT_ID, SWARUP_ID,  date(2000,8,11),  date(2024,4,1),  1400,100,1500,3),
        (DIPAM_ID,     "dipam.barman",       "dipambarman3@gmail.com",         SR_DEV_DESIG_ID,    ENG_DEPT_ID,    JANE_ID,    date(1997,6,8),   date(2023,7,20), 3400,600,4000,7),
        (GAUTAM_ID,    "gautam.hazarika",    "gautamhazarika@gmail.com",       TEAM_LEAD_DESIG_ID, QA_DEPT_ID,     JANE_ID,    date(1994,10,22), date(2022,10,1), 4100,500,4600,9),
    ]
    for (emp_id, username, email, desig_id, dept_id, manager_id, dob, doj,
         avail_pts, redeemed_pts, total_pts, version) in employees:
        await db.employees.create(data={
            "employee_id": emp_id, "username": username, "email": email,
            "password_hash": hashed, "designation_id": desig_id, "department_id": dept_id,
            **({"manager_id": manager_id} if manager_id else {}),
            "status_id": ACTIVE_STATUS_ID,
            "date_of_joining": datetime.combine(doj, datetime.min.time()),
            "date_of_birth":   datetime.combine(dob, datetime.min.time()),
            "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
        })
        await db.wallets.create(data={
            "employee_id": emp_id, "available_points": avail_pts,
            "redeemed_points": redeemed_pts, "total_earned_points": total_pts,
            "version": version, "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
        })
        print(f"   ✅ {username:28s}  wallet: {avail_pts:>5} pts")
    print()


async def backfill_audit_fields():
    print("🔧 Backfilling audit fields on early tables...")
    for table in ["department_types", "departments", "designations"]:
        await db.execute_raw(
            f"UPDATE {table} SET created_by='{ADMIN_ID}', updated_by='{ADMIN_ID}' WHERE created_by IS NULL"
        )
        print(f"   ✅ {table}")
    print()


async def seed_employee_roles():
    print("🔐 Assigning employee roles...")
    roles    = await db.roles.find_many()
    role_map = {r.role_code: r.role_id for r in roles}
    for emp_id, role_codes in [
        (ADMIN_ID,     ["SUPER_ADMIN", "HR_ADMIN"]),
        (JANE_ID,      ["MANAGER", "EMPLOYEE"]),
        (PRASUN_ID,    ["MANAGER", "EMPLOYEE"]),
        (GAUTAM_ID,    ["MANAGER", "EMPLOYEE"]),
        (MRINMOY_ID,   ["MANAGER", "EMPLOYEE"]),
        (JOHN_ID,      ["EMPLOYEE"]),
        (ARIJIT_ID,    ["EMPLOYEE"]),
        (SHUBRAJIT_ID, ["EMPLOYEE"]),
        (MIDANKA_ID,   ["EMPLOYEE"]),
        (SWARUP_ID,    ["EMPLOYEE"]),
        (BIKASH_N_ID,  ["EMPLOYEE"]),
        (BINIT_ID,     ["EMPLOYEE"]),
        (ROHIT_ID,     ["EMPLOYEE"]),
        (RISHAV_ID,    ["EMPLOYEE"]),
        (AMINUL_ID,    ["EMPLOYEE"]),
        (BIKASH_B_ID,  ["EMPLOYEE"]),
        (DIPAM_ID,     ["EMPLOYEE"]),
    ]:
        for code in role_codes:
            await db.employee_roles.create(data={
                "employee_id": emp_id, "role_id": role_map[code],
                "assigned_by": ADMIN_ID, "is_active": True,
                "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
            })
        print(f"   ✅ {emp_id}  → {', '.join(role_codes)}")
    print()


async def seed_reward_categories():
    print("🏷️  Seeding reward_categories...")
    for cat_id, name, code, desc in [
        (GIFT_CARD_CAT_ID,   "Gift Cards",  "GIFT_CARD",   "Digital and physical gift cards"),
        (MERCHANDISE_CAT_ID, "Merchandise", "MERCHANDISE", "Company branded merchandise"),
        (EXPERIENCE_CAT_ID,  "Experiences", "EXPERIENCE",  "Events, courses, and experiences"),
        (WELLNESS_CAT_ID,    "Wellness",    "WELLNESS",    "Health and wellness benefits"),
    ]:
        await db.reward_categories.create(data={
            "category_id": cat_id, "category_name": name, "category_code": code,
            "description": desc, "is_active": True,
            "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
        })
        print(f"   ✅ {code}")
    print()


async def seed_reward_catalog():
    print("🎁 Seeding reward_catalog...")
    items = [
        ("Amazon Gift Card $10",  "REW-AMZ-10",        "Amazon digital gift card worth $10",           GIFT_CARD_CAT_ID,    100,100,100, 50),
        ("Amazon Gift Card $25",  "REW-AMZ-25",        "Amazon digital gift card worth $25",           GIFT_CARD_CAT_ID,    250,250,250, 30),
        ("Flipkart Voucher $15",  "REW-FLIP-15",       "Flipkart voucher worth $15",                   GIFT_CARD_CAT_ID,    150,150,150, 40),
        ("Company T-Shirt",       "REW-MERCH-SHIRT",   "Premium company branded T-shirt",              MERCHANDISE_CAT_ID,  200,200,200,100),
        ("Company Hoodie",        "REW-MERCH-HOODIE",  "Premium company branded hoodie",               MERCHANDISE_CAT_ID,  400,400,400, 40),
        ("Company Mug",           "REW-MERCH-MUG",     "Ceramic company branded mug",                  MERCHANDISE_CAT_ID,   80, 80, 80,150),
        ("Udemy Course Voucher",  "REW-LEARN-UDEMY",   "One Udemy course of your choice",              EXPERIENCE_CAT_ID,   300,300,300, 20),
        ("Team Lunch Voucher",    "REW-EXP-LUNCH",     "Lunch for you and your team (up to 5)",        EXPERIENCE_CAT_ID,   500,500,500, 15),
        ("Movie Ticket (2 pax)",  "REW-EXP-MOVIE",     "Two movie tickets at any PVR/INOX",            EXPERIENCE_CAT_ID,   200,200,200, 25),
        ("Gym Membership (1 mo)", "REW-WELL-GYM",      "One month gym membership",                     WELLNESS_CAT_ID,     600,600,600, 10),
        ("Meditation App (1 yr)", "REW-WELL-MEDIT",    "1-year Calm or Headspace subscription",        WELLNESS_CAT_ID,     350,350,350, 20),
        ("Health Checkup Voucher","REW-WELL-HEALTH",   "Comprehensive annual health checkup package",  WELLNESS_CAT_ID,     800,800,800,  8),
    ]
    for name, code, desc, cat_id, default_pts, min_pts, max_pts, stock in items:
        await db.reward_catalog.create(data={
            "reward_name": name, "reward_code": code, "description": desc,
            "default_points": default_pts, "min_points": min_pts, "max_points": max_pts,
            "is_active": True, "category_id": cat_id, "available_stock": stock,
            "created_by": ADMIN_ID, "updated_by": ADMIN_ID, "updated_at": NOW,
        })
        print(f"   ✅ {code:25s}  {default_pts:>4} pts  stock:{stock}")
    print()


async def seed_reviews():
    print("⭐ Seeding reviews + review_category_tags...")
    print("   Formula: raw_points = sum(category_multipliers) × reviewer_weight")
    print()

    # reviewer_id, receiver_id, comment, days_back,
    # tags: [(cat_id, multiplier_float, code_str)], reviewer_weight
    #
    # raw_points computed inline via pts() helper
    reviews_data = [
        # Jane (MANAGER, weight=1.3) reviewing team
        (JANE_ID,    JOHN_ID,       "Exceptional delivery of the auth module with superb test coverage.",            58,
         [(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP"),(RC_INNOVATION_ID,M_INNOVATION,"INNOVATION")], W_MANAGER),
        (JANE_ID,    ARIJIT_ID,     "Strong contribution to the API refactor. Clean code and great documentation.",  55,
         [(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP"),(RC_COLLAB_ID,M_COLLAB,"COLLABORATION")], W_MANAGER),
        (JANE_ID,    SHUBRAJIT_ID,  "Good effort on the dashboard component. Solid delivery across the sprint.",     50,
         [(RC_COLLAB_ID,M_COLLAB,"COLLABORATION"),(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP")], W_MANAGER),
        (JANE_ID,    DIPAM_ID,      "Dipam led the microservices migration flawlessly.",                             45,
         [(RC_LEADERSHIP_ID,M_LEADERSHIP,"LEADERSHIP"),(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP")], W_MANAGER),
        (JANE_ID,    SWARUP_ID,     "Swarup revamped the entire CI pipeline, cutting build time by 40%.",           38,
         [(RC_INNOVATION_ID,M_INNOVATION,"INNOVATION"),(RC_LEADERSHIP_ID,M_LEADERSHIP,"LEADERSHIP")], W_MANAGER),
        (JANE_ID,    PRASUN_ID,     "Prasun successfully on-boarded 4 new engineers this quarter.",                  28,
         [(RC_LEADERSHIP_ID,M_LEADERSHIP,"LEADERSHIP"),(RC_COLLAB_ID,M_COLLAB,"COLLABORATION")], W_MANAGER),
        (JANE_ID,    GAUTAM_ID,     "Gautam's QA leadership prevented 3 critical prod incidents this month.",         8,
         [(RC_LEADERSHIP_ID,M_LEADERSHIP,"LEADERSHIP"),(RC_INNOVATION_ID,M_INNOVATION,"INNOVATION")], W_MANAGER),

        # Prasun (MANAGER, weight=1.3) reviewing team
        (PRASUN_ID,  JOHN_ID,       "John took full ownership of the payment gateway integration.",                  52,
         [(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP"),(RC_COLLAB_ID,M_COLLAB,"COLLABORATION")], W_MANAGER),
        (PRASUN_ID,  MIDANKA_ID,    "Midanka ramped up quickly and delivered solid UI components.",                  40,
         [(RC_COLLAB_ID,M_COLLAB,"COLLABORATION"),(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP")], W_MANAGER),
        (PRASUN_ID,  BIKASH_N_ID,   "Good infrastructure task delivery and solid team collaboration.",               30,
         [(RC_COLLAB_ID,M_COLLAB,"COLLABORATION"),(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP")], W_MANAGER),

        # Gautam (MANAGER, weight=1.3) reviewing QA team
        (GAUTAM_ID,  RISHAV_ID,     "Rishav automated the entire regression suite. Huge QA win.",                   48,
         [(RC_INNOVATION_ID,M_INNOVATION,"INNOVATION"),(RC_LEADERSHIP_ID,M_LEADERSHIP,"LEADERSHIP")], W_MANAGER),
        (GAUTAM_ID,  MRINMOY_ID,    "Mrinmoy built the QA test framework from scratch this quarter.",               35,
         [(RC_LEADERSHIP_ID,M_LEADERSHIP,"LEADERSHIP"),(RC_INNOVATION_ID,M_INNOVATION,"INNOVATION")], W_MANAGER),
        (GAUTAM_ID,  BINIT_ID,      "Binit wrote thorough unit tests for the notification service.",                 15,
         [(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP"),(RC_COLLAB_ID,M_COLLAB,"COLLABORATION")], W_MANAGER),

        # Mrinmoy (MANAGER, weight=1.3) reviewing
        (MRINMOY_ID, ARIJIT_ID,     "Arijit fixed critical prod bugs under pressure — excellent composure.",         42,
         [(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP"),(RC_INNOVATION_ID,M_INNOVATION,"INNOVATION")], W_MANAGER),
        (MRINMOY_ID, ROHIT_ID,      "Rohit showed strong initiative and delivered his first sprint ahead of schedule.", 22,
         [(RC_OWNERSHIP_ID,M_OWNERSHIP,"OWNERSHIP"),(RC_COLLAB_ID,M_COLLAB,"COLLABORATION")], W_MANAGER),
    ]

    for reviewer_id, receiver_id, comment, dback, tags, weight in reviews_data:
        review_id  = uid()
        review_at  = days_ago(dback)
        raw_points = pts([t[1] for t in tags], weight)

        await db.reviews.create(data={
            "review_id":   review_id,
            "reviewer_id": reviewer_id,
            "receiver_id": receiver_id,
            "comment":     comment,
            "status_id":   REVIEW_ACTIVE_ID,
            "raw_points":  raw_points,
            "review_at":   review_at,
            "created_by":  reviewer_id,
            "updated_by":  reviewer_id,
            "updated_at":  review_at,
        })
        for cat_id, mult, code in tags:
            await db.review_category_tags.create(data={
                "review_id":              review_id,
                "category_id":            cat_id,
                "multiplier_snapshot":    str(mult),
                "category_code_snapshot": code,
            })
        tags_str = " + ".join(f"{t[2]}(×{t[1]})" for t in tags)
        print(f"   ✅ pts={raw_points:>6.4f}  weight=×{weight}  [{tags_str}]")

    print(f"\n   📊 15 reviews + 30 category tags seeded\n")


async def seed_transactions():
    print("💰 Seeding transactions...")
    wallets    = await db.wallets.find_many()
    wallet_map = {w.employee_id: w.wallet_id for w in wallets}

    txn_data = [
        (JOHN_ID,       200, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Q1 performance review credit",                  "TXN-001", 58),
        (JOHN_ID,       300, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Q2 performance review credit",                  "TXN-002", 45),
        (JOHN_ID,       500, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Company Hoodie",            "TXN-003", 30),
        (ARIJIT_ID,     350, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Auth module delivery bonus",                    "TXN-004", 55),
        (ARIJIT_ID,     280, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "API refactor recognition",                      "TXN-005", 40),
        (ARIJIT_ID,     200, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Amazon Gift Card $25",      "TXN-006", 20),
        (SHUBRAJIT_ID,  210, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Dashboard sprint credit",                       "TXN-007", 50),
        (SHUBRAJIT_ID,  150, CREDIT_TYPE_ID,            TXN_PENDING_ID,  "Pending Q3 review credit",                      "TXN-008", 10),
        (PRASUN_ID,     450, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Team lead quarterly bonus",                     "TXN-009", 56),
        (PRASUN_ID,     380, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "On-boarding achievement award",                 "TXN-010", 27),
        (PRASUN_ID,     300, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Udemy Course",              "TXN-011", 18),
        (DIPAM_ID,      550, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Microservices migration leadership award",      "TXN-012", 44),
        (DIPAM_ID,      420, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Senior dev monthly performance credit",         "TXN-013", 25),
        (DIPAM_ID,      600, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Health Checkup Voucher",    "TXN-014", 12),
        (GAUTAM_ID,     480, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "QA leadership quarterly award",                 "TXN-015", 53),
        (GAUTAM_ID,     500, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Incident prevention recognition",               "TXN-016", 22),
        (GAUTAM_ID,     500, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Gym Membership",            "TXN-017",  8),
        (MRINMOY_ID,    430, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Test framework build achievement",              "TXN-018", 34),
        (MRINMOY_ID,    400, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Company Hoodie",            "TXN-019", 14),
        (SWARUP_ID,     420, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "CI pipeline optimisation award",                "TXN-020", 37),
        (SWARUP_ID,     250, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Amazon Gift Card $25",      "TXN-021", 16),
        (RISHAV_ID,     390, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Regression automation credit",                  "TXN-022", 47),
        (RISHAV_ID,     200, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Movie Ticket (2 pax)",      "TXN-023", 11),
        (BIKASH_N_ID,   260, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Infrastructure task completion credit",         "TXN-024", 29),
        (BIKASH_N_ID,   100, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Company Mug",               "TXN-025",  6),
        (MIDANKA_ID,    190, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "UI components delivery credit",                 "TXN-026", 39),
        (BINIT_ID,      130, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "Unit test coverage improvement award",          "TXN-027", 14),
        (BIKASH_B_ID,   240, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "DevOps infra delivery credit",                  "TXN-028", 32),
        (BIKASH_B_ID,   100, REWARD_REDEMPTION_TYPE_ID, TXN_APPROVED_ID, "Reward redemption — Amazon Gift Card $10",      "TXN-029", 10),
        (ROHIT_ID,       84, CREDIT_TYPE_ID,            TXN_APPROVED_ID, "First sprint delivery credit",                  "TXN-030", 21),
        (AMINUL_ID,      60, CREDIT_TYPE_ID,            TXN_PENDING_ID,  "Onboarding peer review credit (pending)",       "TXN-031",  5),
    ]
    for emp_id, amount, type_id, status_id, desc, ref, dback in txn_data:
        txn_at = days_ago(dback)
        await db.transactions.create(data={
            "wallet_id": wallet_map[emp_id], "amount": amount,
            "transaction_type_id": type_id, "status_id": status_id,
            "description": desc, "reference_number": ref,
            "transaction_at": txn_at, "created_by": emp_id,
            "updated_by": emp_id, "updated_at": txn_at,
        })
        sign = "+" if type_id == CREDIT_TYPE_ID else "-"
        print(f"   ✅ {ref:<10}  {sign}{amount:<5}  {desc}")
    print(f"\n   📊 31 transactions seeded\n")


async def seed_reward_history():
    print("🎀 Seeding reward_history...")
    wallets    = await db.wallets.find_many()
    wallet_map = {w.employee_id: w.wallet_id for w in wallets}
    catalog    = await db.reward_catalog.find_many()
    cat_map    = {c.reward_code: c for c in catalog}

    for emp_id, reward_code, points, comment, dback in [
        (JOHN_ID,     "REW-MERCH-HOODIE",  400, "Redeemed as end-of-year reward",              30),
        (ARIJIT_ID,   "REW-AMZ-25",        250, "Gift card for birthday month",                20),
        (PRASUN_ID,   "REW-LEARN-UDEMY",   300, "Upskilling — cloud architecture course",      18),
        (DIPAM_ID,    "REW-WELL-HEALTH",   800, "Annual health checkup package",               12),
        (GAUTAM_ID,   "REW-WELL-GYM",      600, "Monthly gym membership",                       8),
        (MRINMOY_ID,  "REW-MERCH-HOODIE",  400, "Performance milestone reward",                14),
        (SWARUP_ID,   "REW-AMZ-25",        250, "CI/CD pipeline achievement reward",           16),
        (RISHAV_ID,   "REW-EXP-MOVIE",     200, "Team recognition — movie outing",             11),
        (BIKASH_N_ID, "REW-MERCH-MUG",      80, "First redemption milestone",                   6),
        (BIKASH_B_ID, "REW-AMZ-10",         100, "Spot reward for infra delivery",              10),
    ]:
        granted_at = days_ago(dback)
        await db.reward_history.create(data={
            "wallet_id": wallet_map[emp_id], "catalog_id": cat_map[reward_code].catalog_id,
            "granted_by": ADMIN_ID, "points": points, "comment": comment,
            "granted_at": granted_at, "created_by": emp_id,
            "updated_by": emp_id, "updated_at": granted_at,
        })
        print(f"   ✅ {reward_code:25s}  {points:>4} pts")
    print()


async def seed_notifications():
    print("🔔 Seeding notifications...")
    for emp_id, title, message, ntype, is_read, email_sent, dback in [
        (JOHN_ID,      "Points Credited",         "You received 200 points for your Q1 performance review.",                 "POINTS_CREDIT",   True,  True,  58),
        (ARIJIT_ID,    "Points Credited",         "You received 350 points for the auth module delivery bonus.",             "POINTS_CREDIT",   True,  True,  55),
        (DIPAM_ID,     "Points Credited",         "You received 550 points for leading the microservices migration.",        "POINTS_CREDIT",   True,  True,  44),
        (GAUTAM_ID,    "Points Credited",         "You received 480 points for QA leadership this quarter.",                 "POINTS_CREDIT",   True,  True,  53),
        (PRASUN_ID,    "Points Credited",         "You received 450 points as team lead quarterly bonus.",                   "POINTS_CREDIT",   True,  True,  56),
        (JOHN_ID,      "Reward Redeemed",         "Your redemption of Company Hoodie (400 pts) has been confirmed.",         "REWARD_REDEEMED", True,  True,  30),
        (ARIJIT_ID,    "Reward Redeemed",         "Your Amazon Gift Card $25 redemption has been processed.",                "REWARD_REDEEMED", True,  True,  20),
        (MIDANKA_ID,   "Welcome to the Team!",    "Welcome Midanka! Your account is all set. Start exploring your rewards.", "WELCOME",         True,  True,  39),
        (AMINUL_ID,    "Welcome to the Team!",    "Welcome Aminul! Your account is all set. Start exploring your rewards.",  "WELCOME",         False, False,  5),
        (ROHIT_ID,     "Review Received",         "You received a new recognition from mrinmoy.kashyap. Check it out!",     "REVIEW_RECEIVED", True,  True,  22),
        (BINIT_ID,     "Review Received",         "You received a new recognition from gautam.hazarika. Keep it up!",       "REVIEW_RECEIVED", False, True,  15),
        (SHUBRAJIT_ID, "Points Credited",         "You received 210 points for your dashboard sprint contribution.",         "POINTS_CREDIT",   True,  True,  50),
        (SWARUP_ID,    "Achievement Unlocked",    "Your CI pipeline work saved 40% build time. Outstanding achievement!",   "ACHIEVEMENT",     True,  True,  37),
        (RISHAV_ID,    "Points Credited",         "You received 390 points for automating the regression suite.",           "POINTS_CREDIT",   False, True,  47),
        (PRASUN_ID,    "Team Announcement",       "Q4 performance reviews are now open. Please submit your reviews by Jan 15.", "ANNOUNCEMENT",False, True,   3),
    ]:
        notif_id   = uid()
        created_at = days_ago(dback)
        read_at    = (created_at + timedelta(hours=2)).isoformat() if is_read else None
        read_at_sql = f"'{read_at}'" if read_at else "NULL"
        safe_title   = title.replace("'", "''")
        safe_message = message.replace("'", "''")
        await db.execute_raw(f"""
            INSERT INTO notifications
                (notification_id, employee_id, title, message, type,
                 is_read, email_sent, send_attempts, created_at, read_at)
            VALUES (
                '{notif_id}', '{emp_id}', '{safe_title}', '{safe_message}', '{ntype}',
                {str(is_read).lower()}, {str(email_sent).lower()}, 1,
                '{created_at.isoformat()}', {read_at_sql}
            )
        """)
        status = "read  " if is_read else "unread"
        print(f"   ✅ {ntype:20s}  {status}  {title[:38]}")
    print()


async def seed_audit_log():
    print("📝 Seeding audit_log...")
    for table, record_id, operation, old_vals, new_vals, performer, dback in [
        ("employees",      JOHN_ID,           "INSERT", None, {"username":"john.doe","status":"ACTIVE"},                    ADMIN_ID,  60),
        ("employees",      ARIJIT_ID,         "INSERT", None, {"username":"arijit.banik","status":"ACTIVE"},                ADMIN_ID,  59),
        ("employees",      MIDANKA_ID,        "INSERT", None, {"username":"midanka.lahon","status":"ACTIVE"},               ADMIN_ID,  39),
        ("employees",      AMINUL_ID,         "INSERT", None, {"username":"aminul.islam","status":"ACTIVE"},                ADMIN_ID,   5),
        ("wallets",        JOHN_ID,           "UPDATE", {"available_points":1700}, {"available_points":1500},              ADMIN_ID,  30),
        ("wallets",        DIPAM_ID,          "UPDATE", {"available_points":3200}, {"available_points":2600},              ADMIN_ID,  12),
        ("wallets",        GAUTAM_ID,         "UPDATE", {"available_points":4500}, {"available_points":3900},              ADMIN_ID,   8),
        ("reviews",        uid(),             "INSERT", None, {"reviewer":"jane.smith","receiver":"john.doe"},              JANE_ID,   58),
        ("reviews",        uid(),             "INSERT", None, {"reviewer":"gautam.hazarika","receiver":"rishav.bora"},      GAUTAM_ID, 48),
        ("reviews",        uid(),             "INSERT", None, {"reviewer":"jane.smith","receiver":"dipam.barman"},          JANE_ID,   45),
        ("reward_history", uid(),             "INSERT", None, {"reward":"Company Hoodie","employee":"john.doe","pts":400},  ADMIN_ID,  30),
        ("reward_history", uid(),             "INSERT", None, {"reward":"Gym Membership","employee":"gautam","pts":600},    ADMIN_ID,   8),
        ("employee_roles", uid(),             "INSERT", None, {"employee":"prasun.chakraborty","role":"MANAGER"},           ADMIN_ID,  56),
        ("designations",   TEAM_LEAD_DESIG_ID,"INSERT", None, {"code":"TEAM_LEAD","level":2},                              ADMIN_ID,  60),
        ("route_permissions",uid(),           "INSERT", None, {"route":"POST:/v1/auth/login","role":"EMPLOYEE"},            ADMIN_ID,  60),
    ]:
        old_sql = f"'{json.dumps(old_vals)}'::jsonb" if old_vals else "NULL"
        new_sql = f"'{json.dumps(new_vals)}'::jsonb"
        perf_at = days_ago(dback)
        await db.execute_raw(f"""
            INSERT INTO audit_log
                (audit_id, table_name, record_id, operation_type,
                 old_values, new_values, performed_by,
                 ip_address, user_agent, performed_at)
            VALUES (
                '{uid()}', '{table}', '{record_id}', '{operation}',
                {old_sql}, {new_sql}, '{performer}',
                '127.0.0.1', 'seed-script/3.0', '{perf_at.isoformat()}'
            )
        """)
        print(f"   ✅ {operation:6s}  {table}")
    print()


async def main():
    await db.connect()
    try:
        print("=" * 65)
        print("🌱  EMPLOYEE REWARDS SYSTEM — DATABASE SEED v3")
        print("    Formula: raw_points = sum(multipliers) × reviewer_weight")
        print("    Categories: OWNERSHIP×1.2  INNOVATION×1.3  COLLABORATION×1.1  LEADERSHIP×1.4")
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
        await seed_review_categories()
        await seed_employee_roles()
        await seed_reward_categories()
        await seed_reward_catalog()
        await seed_reviews()
        await seed_transactions()
        await seed_reward_history()
        await seed_notifications()
        await seed_audit_log()

        print("=" * 65)
        print("🎉  SEED COMPLETE!")
        print("=" * 65)
        print()
        print("📝 Login credentials (password for all):", TEST_PASSWORD)
        print()
        print("   SUPER_ADMIN + HR_ADMIN:  admin.user")
        print("   MANAGER + EMPLOYEE:      jane.smith | prasun.chakraborty | mrinmoy.kashyap | gautam.hazarika")
        print("   EMPLOYEE:                john.doe | arijit.banik | shubrajit.deb | midanka.lahon")
        print("                            swarup.das | bikash.nath | binit.goswami | rohit.sah")
        print("                            rishav.bora | aminul.islam | bikash.bora | dipam.barman")
        print()
        print("📊 Summary:")
        print("   17 employees  |  17 wallets  |  4 review categories (positive only)")
        print("   15 reviews    |  30 category tags  |  31 transactions")
        print("   10 reward redemptions  |  15 notifications  |  15 audit entries")
        print()
        print("⚠️  route_permissions → run seed_routes.py next")
        print()
    except Exception as e:
        print(f"\n❌ Seed failed: {e}")
        import traceback; traceback.print_exc()
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())