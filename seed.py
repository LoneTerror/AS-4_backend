"""
Complete database seeding script for Employee Rewards System.
Self-contained — seeds everything from scratch in the correct order.
~30 entries per table. Strictly matches schema.prisma.

Run with:
    python seed.py

Tables seeded (in dependency order):
    status_master          — EMPLOYEE, TRANSACTION, REVIEW statuses
    transaction_types      — CREDIT, DEBIT, REWARD_REDEMPTION, BONUS, ADJUSTMENT, REVERSAL
    roles                  — SUPER_ADMIN, HR_ADMIN, MANAGER, EMPLOYEE, AUDITOR, TEAM_LEAD, DIRECTOR
    department_types       — TECH, MGMT, OPERATIONS, FINANCE, LEGAL, MARKETING
    departments            — 10 departments
    designations           — 10 designations
    employees              — 30 employees (1 admin bootstrap + 29 rest)
    wallets                — one per employee (auto via seed)
    employee_roles         — role assignments for all employees
    reward_categories      — GIFT_CARD, MERCHANDISE, EXPERIENCE, WELLNESS, LEARNING
    reward_catalog         — 30 reward items (STABLE IDs)
    review_categories      — 10 positive categories only
    reviews                — 30 reviews
    review_category_tags   — ~2 tags per review
    transactions           — 30 transactions
    reward_history         — 30 redemption entries
    audit_log              — 30 audit entries
    notifications          — 30 notifications
    NOTE: route_permissions are auto-handled by the system on startup.

AUDIT MIGRATION NOTE:
    The audit trigger migration (migration.sql) requires:
      - At least one row in departments         ← seeded here
      - At least one row in designations        ← seeded here
      - A status_master row where
          entity_type = 'EMPLOYEE'
          status_code = 'ACTIVE'               ← S_EMP_ACTIVE seeded here

    Run order:
        1. python seed.py
        2. prisma migrate deploy   (runs migration.sql — creates sentinel + triggers)
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
import uuid
import json
from datetime import date, datetime, timezone, timedelta

from src.prisma.client import db
from src.core.security import hash_password


# ─────────────────────────────────────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────────────────────────────────────
TEST_PASSWORD = "Password123!"
TODAY = date.today()
NOW = datetime.now(timezone.utc)

# Sentinel UUID — must match migration.sql exactly.
# This employee is the fallback "performed_by" for any DB write that happens
# outside the application (migrations, DBA sessions, background jobs that
# have no authenticated user).  It is created by the migration, NOT the seed,
# because the triggers must already exist before any further seeding runs.
SYSTEM_SENTINEL_ID = "00000000-0000-0000-0000-000000000000"


def uid() -> str:
    return str(uuid.uuid4())


def dt(d: date) -> datetime:
    """Convert date → UTC datetime (midnight)."""
    return datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# FIXED IDs
# ─────────────────────────────────────────────────────────────────────────────

# ── Status Master ─────────────────────────────────────────────────────────────
# IMPORTANT: S_EMP_ACTIVE must have entity_type='EMPLOYEE' and status_code='ACTIVE'
# because the audit trigger migration looks for exactly that combination to assign
# to the system sentinel employee row.
S_EMP_ACTIVE     = "990e8400-e29b-41d4-a716-446655440000"   # EMPLOYEE / ACTIVE
S_EMP_INACTIVE   = "990e8400-e29b-41d4-a716-446655440001"   # EMPLOYEE / INACTIVE
S_TXN_PENDING    = "990e8400-e29b-41d4-a716-446655440002"   # TRANSACTION / PENDING
S_TXN_APPROVED   = "990e8400-e29b-41d4-a716-446655440003"   # TRANSACTION / APPROVED
S_TXN_REJECTED   = "990e8400-e29b-41d4-a716-446655440004"   # TRANSACTION / REJECTED
S_TXN_SUCCESS    = "990e8400-e29b-41d4-a716-446655440007"   # TRANSACTION / SUCCESS
S_TXN_FAILED     = "990e8400-e29b-41d4-a716-446655440008"   # TRANSACTION / FAILED
S_REV_ACTIVE     = "990e8400-e29b-41d4-a716-446655440005"   # REVIEW / REVIEW_ACTIVE
S_REV_DELETED    = "990e8400-e29b-41d4-a716-446655440006"   # REVIEW / REVIEW_DELETED

# Convenience alias — use S_EMP_ACTIVE everywhere an employee status is needed
S_ACTIVE   = S_EMP_ACTIVE
S_INACTIVE = S_EMP_INACTIVE

# ── Transaction Types ─────────────────────────────────────────────────────────
TT_CREDIT        = "bb0e8400-e29b-41d4-a716-446655440001"
TT_REDEMPTION    = "bb0e8400-e29b-41d4-a716-446655440002"
TT_BONUS         = "bb0e8400-e29b-41d4-a716-446655440003"
TT_ADJUSTMENT    = "bb0e8400-e29b-41d4-a716-446655440004"
TT_REVERSAL      = "bb0e8400-e29b-41d4-a716-446655440005"
TT_DEBIT         = "bb0e8400-e29b-41d4-a716-446655440006"

# ── Roles ─────────────────────────────────────────────────────────────────────
R_SUPER_ADMIN    = "ee0e8400-e29b-41d4-a716-446655440001"
R_HR_ADMIN       = "ee0e8400-e29b-41d4-a716-446655440002"
R_MANAGER        = "ee0e8400-e29b-41d4-a716-446655440003"
R_EMPLOYEE       = "ee0e8400-e29b-41d4-a716-446655440004"
R_AUDITOR        = "ee0e8400-e29b-41d4-a716-446655440005"
R_TEAM_LEAD      = "ee0e8400-e29b-41d4-a716-446655440006"
R_DIRECTOR       = "ee0e8400-e29b-41d4-a716-446655440007"

# ── Department Types ──────────────────────────────────────────────────────────
DT_TECH          = "aa0e8400-e29b-41d4-a716-446655440001"
DT_MGMT          = "aa0e8400-e29b-41d4-a716-446655440002"
DT_OPS           = "aa0e8400-e29b-41d4-a716-446655440003"
DT_FINANCE       = "aa0e8400-e29b-41d4-a716-446655440004"
DT_LEGAL         = "aa0e8400-e29b-41d4-a716-446655440005"
DT_MARKETING     = "aa0e8400-e29b-41d4-a716-446655440006"

# ── Departments ───────────────────────────────────────────────────────────────
D_ENG            = "770e8400-e29b-41d4-a716-446655440001"
D_PLATFORM       = "770e8400-e29b-41d4-a716-446655440002"
D_QA             = "770e8400-e29b-41d4-a716-446655440003"
D_HR             = "770e8400-e29b-41d4-a716-446655440004"
D_EXEC           = "770e8400-e29b-41d4-a716-446655440005"
D_OPS            = "770e8400-e29b-41d4-a716-446655440006"
D_FINANCE        = "770e8400-e29b-41d4-a716-446655440007"
D_LEGAL          = "770e8400-e29b-41d4-a716-446655440008"
D_MARKETING      = "770e8400-e29b-41d4-a716-446655440009"
D_DEVOPS         = "770e8400-e29b-41d4-a716-44665544000a"

# ── Designations ──────────────────────────────────────────────────────────────
DES_SYS_ADMIN    = "660e8400-e29b-41d4-a716-446655440001"
DES_DIRECTOR     = "660e8400-e29b-41d4-a716-446655440002"
DES_ENG_MGR      = "660e8400-e29b-41d4-a716-446655440003"
DES_TEAM_LEAD    = "660e8400-e29b-41d4-a716-446655440004"
DES_SR_DEV       = "660e8400-e29b-41d4-a716-446655440005"
DES_DEV          = "660e8400-e29b-41d4-a716-446655440006"
DES_QA_LEAD      = "660e8400-e29b-41d4-a716-446655440007"
DES_QA_ENG       = "660e8400-e29b-41d4-a716-446655440008"
DES_HR_MGR       = "660e8400-e29b-41d4-a716-446655440009"
DES_HR_EXEC      = "660e8400-e29b-41d4-a716-44665544000a"

# ── Employees (30 total) ──────────────────────────────────────────────────────
EMP_ADMIN        = "110e8400-e29b-41d4-a716-446655440001"
EMP_JANE         = "110e8400-e29b-41d4-a716-446655440002"
EMP_JOHN         = "110e8400-e29b-41d4-a716-446655440003"
EMP_ARIJIT       = "110e8400-e29b-41d4-a716-446655440004"
EMP_SHUBRAJIT    = "110e8400-e29b-41d4-a716-446655440005"
EMP_PRASUN       = "110e8400-e29b-41d4-a716-446655440006"
EMP_ALICE        = "110e8400-e29b-41d4-a716-446655440007"
EMP_BOB          = "110e8400-e29b-41d4-a716-446655440008"
EMP_CAROL        = "110e8400-e29b-41d4-a716-446655440009"
EMP_DAVE         = "110e8400-e29b-41d4-a716-44665544000a"
EMP_EVE          = "110e8400-e29b-41d4-a716-44665544000b"
EMP_FRANK        = "110e8400-e29b-41d4-a716-44665544000c"
EMP_GRACE        = "110e8400-e29b-41d4-a716-44665544000d"
EMP_HENRY        = "110e8400-e29b-41d4-a716-44665544000e"
EMP_IVY          = "110e8400-e29b-41d4-a716-44665544000f"
EMP_JAMES        = "110e8400-e29b-41d4-a716-446655440010"
EMP_KATE         = "110e8400-e29b-41d4-a716-446655440011"
EMP_LEO          = "110e8400-e29b-41d4-a716-446655440012"
EMP_MIA          = "110e8400-e29b-41d4-a716-446655440013"
EMP_NOAH         = "110e8400-e29b-41d4-a716-446655440014"
EMP_OLIVIA       = "110e8400-e29b-41d4-a716-446655440015"
EMP_PETER        = "110e8400-e29b-41d4-a716-446655440016"
EMP_QUINN        = "110e8400-e29b-41d4-a716-446655440017"
EMP_RACHEL       = "110e8400-e29b-41d4-a716-446655440018"
EMP_SAM          = "110e8400-e29b-41d4-a716-446655440019"
EMP_TINA         = "110e8400-e29b-41d4-a716-44665544001a"
EMP_UMAR         = "110e8400-e29b-41d4-a716-44665544001b"
EMP_VERA         = "110e8400-e29b-41d4-a716-44665544001c"
EMP_WILL         = "110e8400-e29b-41d4-a716-44665544001d"
EMP_XENA         = "110e8400-e29b-41d4-a716-44665544001e"

# ── Review Categories ─────────────────────────────────────────────────────────
RC_OWNERSHIP     = "dd0e8400-e29b-41d4-a716-446655440001"
RC_INNOVATION    = "dd0e8400-e29b-41d4-a716-446655440002"
RC_COLLAB        = "dd0e8400-e29b-41d4-a716-446655440003"
RC_LEADERSHIP    = "dd0e8400-e29b-41d4-a716-446655440004"
RC_QUALITY       = "dd0e8400-e29b-41d4-a716-446655440005"
RC_MENTORSHIP    = "dd0e8400-e29b-41d4-a716-446655440006"
RC_DELIVERY      = "dd0e8400-e29b-41d4-a716-446655440007"
RC_PROBLEM_SOLVE = "dd0e8400-e29b-41d4-a716-446655440008"
RC_ADAPTABILITY  = "dd0e8400-e29b-41d4-a716-446655440009"
RC_CUSTOMER      = "dd0e8400-e29b-41d4-a716-44665544000a"

# ── Reward Categories ─────────────────────────────────────────────────────────
RWCAT_GIFT       = "cc0e8400-e29b-41d4-a716-446655440001"
RWCAT_MERCH      = "cc0e8400-e29b-41d4-a716-446655440002"
RWCAT_EXP        = "cc0e8400-e29b-41d4-a716-446655440003"
RWCAT_WELLNESS   = "cc0e8400-e29b-41d4-a716-446655440004"
RWCAT_LEARNING   = "cc0e8400-e29b-41d4-a716-446655440005"

# ── Reward Catalog (STABLE IDs) ───────────────────────────────────────────────
CAT_AMZ_010      = "ed0e8400-e29b-41d4-a716-446655440001"
CAT_AMZ_025      = "ed0e8400-e29b-41d4-a716-446655440002"
CAT_AMZ_050      = "ed0e8400-e29b-41d4-a716-446655440003"
CAT_FLK_020      = "ed0e8400-e29b-41d4-a716-446655440004"
CAT_SWG_015      = "ed0e8400-e29b-41d4-a716-446655440005"
CAT_NET_001      = "ed0e8400-e29b-41d4-a716-446655440006"
CAT_TSH_001      = "ed0e8400-e29b-41d4-a716-446655440007"
CAT_HOD_001      = "ed0e8400-e29b-41d4-a716-446655440008"
CAT_CAP_001      = "ed0e8400-e29b-41d4-a716-446655440009"
CAT_MUG_001      = "ed0e8400-e29b-41d4-a716-44665544000a"
CAT_BAG_001      = "ed0e8400-e29b-41d4-a716-44665544000b"
CAT_BTL_001      = "ed0e8400-e29b-41d4-a716-44665544000c"
CAT_LNC_001      = "ed0e8400-e29b-41d4-a716-44665544000d"
CAT_DIN_001      = "ed0e8400-e29b-41d4-a716-44665544000e"
CAT_MOV_001      = "ed0e8400-e29b-41d4-a716-44665544000f"
CAT_STA_001      = "ed0e8400-e29b-41d4-a716-446655440010"
CAT_SPA_001      = "ed0e8400-e29b-41d4-a716-446655440011"
CAT_AMU_001      = "ed0e8400-e29b-41d4-a716-446655440012"
CAT_GYM_001      = "ed0e8400-e29b-41d4-a716-446655440013"
CAT_YOG_001      = "ed0e8400-e29b-41d4-a716-446655440014"
CAT_MHT_001      = "ed0e8400-e29b-41d4-a716-446655440015"
CAT_HLT_001      = "ed0e8400-e29b-41d4-a716-446655440016"
CAT_ERG_001      = "ed0e8400-e29b-41d4-a716-446655440017"
CAT_UDM_001      = "ed0e8400-e29b-41d4-a716-446655440018"
CAT_CRS_001      = "ed0e8400-e29b-41d4-a716-446655440019"
CAT_ORL_001      = "ed0e8400-e29b-41d4-a716-44665544001a"
CAT_BKS_030      = "ed0e8400-e29b-41d4-a716-44665544001b"
CAT_AWS_CPE      = "ed0e8400-e29b-41d4-a716-44665544001c"
CAT_GCP_001      = "ed0e8400-e29b-41d4-a716-44665544001d"
CAT_CONF_001     = "ed0e8400-e29b-41d4-a716-44665544001e"


# ─────────────────────────────────────────────────────────────────────────────
# CLEAN
# ─────────────────────────────────────────────────────────────────────────────
async def clean_db():
    """
    Delete all seed data in the correct order, preserving the system sentinel.

    The schema has circular created_by/updated_by FKs pointing back to
    employees from almost every table (department_types, departments,
    designations, roles, status_master, reward_categories, review_categories,
    reward_catalog, wallets, employee_roles, etc.).

    This means you CANNOT simply delete employees first — Postgres will refuse
    because those other tables still reference employee UUIDs via created_by.

    Correct approach:
      Step 1 — NULL out all created_by/updated_by columns that point to
                employees, across every table that has them.  This breaks the
                circular references so employees can be deleted.
      Step 2 — Delete leaf tables first (no other table FKs into them).
      Step 3 — Delete employees (non-sentinel only).
      Step 4 — Delete the remaining lookup tables (departments, designations,
                department_types, status_master) which are now safe.
    """
    print("🧹 Cleaning existing data...")

    # ── Step 1: NULL out all created_by / updated_by back-references ──────────
    # Every table that has a created_by or updated_by FK to employees must be
    # cleared here before we can delete any employee rows.
    null_refs = [
        # (table,                  columns with FK to employees)
        ("audit_log",              ["performed_by"]),
        ("department_types",       ["created_by", "updated_by"]),
        ("departments",            ["created_by", "updated_by"]),
        ("designations",           ["created_by", "updated_by"]),
        ("roles",                  ["created_by", "updated_by"]),
        ("route_permissions",      ["created_by", "updated_by"]),
        ("status_master",          ["created_by", "updated_by"]),
        ("transaction_types",      ["created_by", "updated_by"]),
        ("review_categories",      ["created_by", "updated_by"]),
        ("reward_categories",      ["created_by", "updated_by"]),
        ("reward_catalog",         ["created_by", "updated_by"]),
        ("employee_roles",         ["assigned_by", "revoked_by", "created_by", "updated_by"]),
        ("wallets",                ["created_by", "updated_by"]),
        ("transactions",           ["created_by", "updated_by"]),
        ("reward_history",         ["granted_by", "created_by", "updated_by"]),
        ("reviews",                ["reviewer_id", "receiver_id", "created_by", "updated_by"]),
        ("refresh_tokens",         []),   # no created_by — employee_id is cascade-deleted
    ]

    for table, cols in null_refs:
        if not cols:
            continue
        set_clause = ", ".join(f"{c} = NULL" for c in cols)
        try:
            await db.execute_raw(f"UPDATE {table} SET {set_clause}")
        except Exception as ex:
            print(f"   ⚠ Could not null refs on {table}: {ex}")

    print("   ✓ Nulled all created_by/updated_by back-references")

    # ── Step 2: Delete leaf tables (strict dependency order) ──────────────────
    # These have no other tables pointing into them (or their FKs are now NULL).
    leaf_deletes = [
        "audit_log",
        "notifications",
        "review_category_tags",
        "reviews",
        "transactions",
        "reward_history",
        "refresh_tokens",
        "employee_roles",
        "wallets",
        "reward_catalog",
        "reward_categories",
        "transaction_types",
        "review_categories",
        "route_permissions",
        "roles",
    ]
    for table in leaf_deletes:
        try:
            await db.execute_raw(f"DELETE FROM {table}")
        except Exception as ex:
            print(f"   ⚠ Could not delete {table}: {ex}")

    print("   ✓ Deleted leaf tables")

    # ── Step 3: Delete non-sentinel employees ─────────────────────────────────
    # The sentinel (00000000-...) must stay if it exists — it was created by
    # the audit migration and the triggers FK into it.
    try:
        await db.execute_raw(
            f"DELETE FROM employees WHERE employee_id != '{SYSTEM_SENTINEL_ID}'"
        )
        print("   ✓ Deleted non-sentinel employees")
    except Exception as ex:
        print(f"   ⚠ Could not delete employees: {ex}")

    # ── Step 4: Delete lookup tables (now safe — no employee refs remain) ─────
    for table in ["designations", "departments", "department_types", "status_master"]:
        try:
            await db.execute_raw(f"DELETE FROM {table}")
        except Exception as ex:
            print(f"   ⚠ Could not delete {table}: {ex}")

    print("   ✓ Deleted lookup tables")
    print("   ✓ Clean complete (sentinel preserved if present)\n")


# ─────────────────────────────────────────────────────────────────────────────
# STATUS MASTER
# ─────────────────────────────────────────────────────────────────────────────
async def seed_status_master():
    print("📋 Seeding status_master...")
    # ┌─────────────────────────────────────────────────────────────────────┐
    # │  CRITICAL FOR AUDIT MIGRATION                                       │
    # │  S_EMP_ACTIVE MUST have entity_type='EMPLOYEE' status_code='ACTIVE' │
    # │  The migration.sql sentinel INSERT queries this exact combination.   │
    # └─────────────────────────────────────────────────────────────────────┘
    rows = [
        # Employee statuses — entity_type = 'EMPLOYEE'
        (S_EMP_ACTIVE,   "ACTIVE",         "Active",      "EMPLOYEE",    "Employee is active and operational"),
        (S_EMP_INACTIVE, "INACTIVE",       "Inactive",    "EMPLOYEE",    "Employee is inactive or disabled"),
        # Transaction statuses — entity_type = 'TRANSACTION'
        (S_TXN_PENDING,  "PENDING",        "Pending",     "TRANSACTION", "Transaction awaiting approval"),
        (S_TXN_APPROVED, "APPROVED",       "Approved",    "TRANSACTION", "Transaction has been approved"),
        (S_TXN_REJECTED, "REJECTED",       "Rejected",    "TRANSACTION", "Transaction has been rejected"),
        (S_TXN_SUCCESS,  "SUCCESS",        "Success",     "TRANSACTION", "Transaction completed successfully"),
        (S_TXN_FAILED,   "FAILED",         "Failed",      "TRANSACTION", "Transaction failed to complete"),
        # Review statuses — entity_type = 'REVIEW'
        (S_REV_ACTIVE,   "REVIEW_ACTIVE",  "Active",      "REVIEW",      "Review is active and visible"),
        (S_REV_DELETED,  "REVIEW_DELETED", "Deleted",     "REVIEW",      "Review has been soft-deleted"),
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
    print(f"   ✅ Seeded {len(rows)} status rows")
    print(f"   ℹ  S_EMP_ACTIVE ({S_EMP_ACTIVE}) → entity_type=EMPLOYEE status_code=ACTIVE")
    print(f"      ↳ Migration sentinel will use this row\n")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION TYPES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_transaction_types():
    print("💳 Seeding transaction_types...")
    rows = [
        (TT_CREDIT,     "Credit",            "CREDIT",            "Points credited from performance review",          True),
        (TT_REDEMPTION, "Reward Redemption", "REWARD_REDEMPTION", "Points deducted when redeeming a reward",          False),
        (TT_BONUS,      "Bonus",             "BONUS",             "Discretionary bonus points granted by HR/manager", True),
        (TT_ADJUSTMENT, "Adjustment",        "ADJUSTMENT",        "Manual adjustment to correct wallet balance",      True),
        (TT_REVERSAL,   "Reversal",          "REVERSAL",          "Reversal of a previously approved transaction",    False),
        (TT_DEBIT,      "Debit",             "DEBIT",             "Points debited for policy violations",             False),
    ]
    for type_id, name, code, desc, is_credit in rows:
        await db.transaction_types.create(data={
            "type_id":     type_id,
            "type_name":   name,
            "type_code":   code,
            "description": desc,
            "is_credit":   is_credit,
            "updated_at":  NOW,
        })
    print(f"   ✅ Seeded {len(rows)} transaction types\n")


# ─────────────────────────────────────────────────────────────────────────────
# ROLES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_roles():
    print("👥 Seeding roles...")
    rows = [
        (R_SUPER_ADMIN, "SUPER_ADMIN", "Super Admin",  "Full unrestricted system access",                "1.5000"),
        (R_HR_ADMIN,    "HR_ADMIN",    "HR Admin",     "Manage employees, departments and designations", "1.2000"),
        (R_MANAGER,     "MANAGER",     "Manager",      "Manage direct reports and approve reviews",      "1.3000"),
        (R_EMPLOYEE,    "EMPLOYEE",    "Employee",     "Standard self-service access",                   "1.0000"),
        (R_AUDITOR,     "AUDITOR",     "Auditor",      "Read-only access to audit logs and reports",     "1.0000"),
        (R_TEAM_LEAD,   "TEAM_LEAD",   "Team Lead",    "Lead a sub-team; peer reviews with extra weight","1.1500"),
        (R_DIRECTOR,    "DIRECTOR",    "Director",     "Senior leadership with org-wide review access",  "1.4000"),
    ]
    for role_id, code, name, desc, weight in rows:
        await db.roles.create(data={
            "role_id":         role_id,
            "role_name":       name,
            "role_code":       code,
            "description":     desc,
            "reviewer_weight": weight,
            "updated_at":      NOW,
        })
        print(f"   ✅ {code:15s}  reviewer_weight={weight}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENT TYPES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_department_types():
    print("🏗️  Seeding department_types...")
    rows = [
        (DT_TECH,      "Technology",  "TECH"),
        (DT_MGMT,      "Management",  "MGMT"),
        (DT_OPS,       "Operations",  "OPS"),
        (DT_FINANCE,   "Finance",     "FINANCE"),
        (DT_LEGAL,     "Legal",       "LEGAL"),
        (DT_MARKETING, "Marketing",   "MARKETING"),
    ]
    for type_id, name, code in rows:
        await db.department_types.create(data={
            "department_type_id": type_id,
            "type_name":          name,
            "type_code":          code,
            "updated_at":         NOW,
        })
    print(f"   ✅ Seeded {len(rows)} department types\n")


# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENTS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_departments():
    print("🏢 Seeding departments...")
    rows = [
        (D_ENG,       "Engineering",             "ENG",       DT_TECH),
        (D_PLATFORM,  "Platform Engineering",    "PLATFORM",  DT_TECH),
        (D_QA,        "Quality Assurance",       "QA",        DT_TECH),
        (D_DEVOPS,    "DevOps & Infrastructure", "DEVOPS",    DT_TECH),
        (D_HR,        "Human Resources",         "HR",        DT_MGMT),
        (D_EXEC,      "Executive",               "EXEC",      DT_MGMT),
        (D_OPS,       "Operations",              "OPS",       DT_OPS),
        (D_FINANCE,   "Finance & Accounting",    "FINANCE",   DT_FINANCE),
        (D_LEGAL,     "Legal & Compliance",      "LEGAL",     DT_LEGAL),
        (D_MARKETING, "Marketing & Growth",      "MARKETING", DT_MARKETING),
    ]
    for dept_id, name, code, type_id in rows:
        await db.departments.create(data={
            "department_id":      dept_id,
            "department_name":    name,
            "department_code":    code,
            "department_type_id": type_id,
            "updated_at":         NOW,
        })
    print(f"   ✅ Seeded {len(rows)} departments\n")


# ─────────────────────────────────────────────────────────────────────────────
# DESIGNATIONS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_designations():
    print("🎖️  Seeding designations...")
    rows = [
        (DES_SYS_ADMIN, "System Administrator", "SYS_ADMIN", 0, "Top-level system administrator with full access"),
        (DES_DIRECTOR,  "Director",             "DIRECTOR",  1, "Senior director overseeing a business unit"),
        (DES_ENG_MGR,   "Engineering Manager",  "ENG_MGR",   2, "Manages engineering teams and technical delivery"),
        (DES_HR_MGR,    "HR Manager",           "HR_MGR",    2, "Manages HR operations and employee lifecycle"),
        (DES_TEAM_LEAD, "Team Lead",            "TEAM_LEAD", 3, "Technical lead for a squad or team"),
        (DES_QA_LEAD,   "QA Lead",              "QA_LEAD",   3, "Leads quality assurance efforts for a product"),
        (DES_SR_DEV,    "Senior Developer",     "SR_DEV",    4, "Senior individual contributor in software development"),
        (DES_DEV,       "Developer",            "DEV",       5, "Mid-level software developer"),
        (DES_QA_ENG,    "QA Engineer",          "QA_ENG",    5, "Quality assurance engineer responsible for testing"),
        (DES_HR_EXEC,   "HR Executive",         "HR_EXEC",   6, "Entry-level HR professional handling daily operations"),
    ]
    for desig_id, name, code, level, desc in rows:
        await db.designations.create(data={
            "designation_id":   desig_id,
            "designation_name": name,
            "designation_code": code,
            "level":            level,
            "description":      desc,
            "is_active":        True,
            "updated_at":       NOW,
        })
        print(f"   ✅ {code:12s}  level={level}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN EMPLOYEE
# ─────────────────────────────────────────────────────────────────────────────
async def seed_admin_employee():
    print("👤 Bootstrapping admin employee...")
    hashed = hash_password(TEST_PASSWORD)
    await db.employees.create(data={
        "employee_id":     EMP_ADMIN,
        "username":        "admin.user",
        "email":           "admin@company.com",
        "password_hash":   hashed,
        "designation_id":  DES_SYS_ADMIN,
        "department_id":   D_HR,
        "status_id":       S_ACTIVE,
        "date_of_joining": dt(date(2018, 1, 1)),
        "date_of_birth":   dt(TODAY),
        "created_by":      EMP_ADMIN,
        "updated_by":      EMP_ADMIN,
        "updated_at":      NOW,
    })
    await db.wallets.create(data={
        "employee_id":         EMP_ADMIN,
        "available_points":    999999,
        "redeemed_points":     0,
        "total_earned_points": 999999,
        "version":             1,
        "created_by":          EMP_ADMIN,
        "updated_by":          EMP_ADMIN,
        "updated_at":          NOW,
    })
    print(f"   ✅ admin.user  (system bootstrap)\n")


# ─────────────────────────────────────────────────────────────────────────────
# REMAINING EMPLOYEES (29 rows)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_employees():
    print("👤 Seeding employees (29 remaining)...")
    hashed = hash_password(TEST_PASSWORD)

    employees = [
        (EMP_JANE,      "jane.smith",         "jane.smith@company.com",         DES_ENG_MGR,   D_ENG,       None,      date(1988, 4, 12), date(2019, 3,  1), 8000,  500,  8500,  3),
        (EMP_ALICE,     "alice.wong",         "alice.wong@company.com",         DES_DIRECTOR,  D_EXEC,      None,      date(1982, 9,  5), date(2017, 6, 15), 12000, 1000, 13000, 5),
        (EMP_GRACE,     "grace.hopper",       "grace.hopper@company.com",       DES_HR_MGR,    D_HR,        None,      date(1986, 11, 3), date(2018, 2, 10), 7000,  300,  7300,  4),
        (EMP_HENRY,     "henry.ford",         "henry.ford@company.com",         DES_TEAM_LEAD, D_ENG,       EMP_JANE,  date(1990, 7, 22), date(2020, 5,  1), 5000,  200,  5200,  2),
        (EMP_IVY,       "ivy.league",         "ivy.league@company.com",         DES_QA_LEAD,   D_QA,        EMP_JANE,  date(1991, 1, 30), date(2021, 1, 20), 4500,  100,  4600,  2),
        (EMP_JAMES,     "james.bond",         "james.bond@company.com",         DES_TEAM_LEAD, D_PLATFORM,  EMP_JANE,  date(1989, 12, 7), date(2020, 8,  1), 6000,  400,  6400,  3),
        (EMP_JOHN,      "john.doe",           "john.doe@company.com",           DES_SR_DEV,    D_ENG,       EMP_HENRY, date(1995, 8, 15), date(2022, 1, 15), 3000,  500,  3500,  6),
        (EMP_ARIJIT,    "arijit.banik",       "arijitb017@gmail.com",           DES_SR_DEV,    D_ENG,       EMP_HENRY, date(2000, 3, 17), date(2023, 3,  1), 2500,  100,  2600,  3),
        (EMP_SHUBRAJIT, "shubrajit.deb",      "shubrajitdeb180603@gmail.com",   DES_SR_DEV,    D_PLATFORM,  EMP_JAMES, date(2003, 6, 18), date(2023, 6,  1), 2200,  0,    2200,  2),
        (EMP_PRASUN,    "prasun.chakraborty", "nothingshere21@gmail.com",       DES_SR_DEV,    D_PLATFORM,  EMP_JAMES, date(1998, 11,25), date(2023, 3,  1), 2800,  200,  3000,  4),
        (EMP_BOB,       "midanka.lahon",      "midankalahon@gmail.com",         DES_SR_DEV,    D_ENG,       EMP_HENRY, date(1993, 2, 14), date(2021, 7,  5), 3500,  300,  3800,  5),
        (EMP_CAROL,     "swarup.das",         "swarup1to3@gmail.com",           DES_SR_DEV,    D_DEVOPS,    EMP_JANE,  date(1994, 5, 20), date(2022, 4,  1), 3200,  100,  3300,  3),
        (EMP_DAVE,      "bikash.nath",        "nathbikash231@gmail.com",        DES_DEV,       D_ENG,       EMP_HENRY, date(1997, 3,  8), date(2023, 9,  1), 1500,  0,    1500,  1),
        (EMP_EVE,       "binit.goswami",      "binitkgsmile2005@gmail.com",     DES_DEV,       D_ENG,       EMP_HENRY, date(1999, 10,15), date(2024, 1, 10), 1200,  0,    1200,  1),
        (EMP_FRANK,     "mrinmoy.kashyap",    "mrinmoykashyap.mk@gmail.com",    DES_DEV,       D_PLATFORM,  EMP_JAMES, date(1996, 7,  4), date(2023, 11, 1), 1800,  200,  2000,  2),
        (EMP_KATE,      "rohit.sah",          "rsah94614@gmail.com",            DES_DEV,       D_PLATFORM,  EMP_JAMES, date(2001, 4, 25), date(2024, 2,  1), 1000,  0,    1000,  1),
        (EMP_LEO,       "rishav.bora",        "rishavbora550@gmail.com",        DES_DEV,       D_ENG,       EMP_HENRY, date(1987, 6, 24), date(2022, 10, 3), 2000,  100,  2100,  2),
        (EMP_MIA,       "aminul.islam",       "animul7535@gmail.com",           DES_DEV,       D_DEVOPS,    EMP_JANE,  date(1999, 2, 10), date(2024, 5,  1), 900,   0,    900,   1),
        (EMP_NOAH,      "bikash.bora",        "borab796@gmail.com",             DES_DEV,       D_ENG,       EMP_HENRY, date(2000, 12, 1), date(2024, 7,  1), 700,   0,    700,   1),
        (EMP_OLIVIA,    "dipam.barman",       "dipambarman3@gmail.com",         DES_QA_ENG,    D_QA,        EMP_IVY,   date(1993, 9, 18), date(2022, 6,  1), 1800,  100,  1900,  2),
        (EMP_PETER,     "gautam.hazarika",    "gautamhazarika01@gmail.com",     DES_QA_ENG,    D_QA,        EMP_IVY,   date(2001, 8,  3), date(2024, 3,  1), 1100,  0,    1100,  1),
        (EMP_QUINN,     "quinn.harley",       "quinn.harley@company.com",       DES_QA_ENG,    D_QA,        EMP_IVY,   date(1998, 5, 11), date(2023, 5,  1), 1400,  50,   1450,  2),
        (EMP_RACHEL,    "rachel.green",       "rachel.green@company.com",       DES_HR_EXEC,   D_HR,        EMP_GRACE, date(1992, 10,22), date(2022, 9,  1), 1600,  0,    1600,  1),
        (EMP_SAM,       "sam.winchester",     "sam.winchester@company.com",     DES_HR_EXEC,   D_HR,        EMP_GRACE, date(1996, 1, 19), date(2023, 1, 10), 1300,  100,  1400,  2),
        (EMP_TINA,      "tina.turner",        "tina.turner@company.com",        DES_SR_DEV,    D_OPS,       None,      date(1990, 11,26), date(2021, 4, 15), 2400,  200,  2600,  3),
        (EMP_UMAR,      "umar.farooq",        "umar.farooq@company.com",        DES_DEV,       D_FINANCE,   None,      date(1994, 8,  7), date(2022, 8,  1), 1700,  0,    1700,  1),
        (EMP_VERA,      "vera.farmiga",       "vera.farmiga@company.com",       DES_DEV,       D_LEGAL,     None,      date(1993, 4,  6), date(2023, 2,  1), 1500,  0,    1500,  1),
        (EMP_WILL,      "will.smith",         "will.smith@company.com",         DES_SR_DEV,    D_MARKETING, None,      date(1991, 9, 25), date(2021, 12, 1), 2600,  300,  2900,  3),
        (EMP_XENA,      "xena.warrior",       "xena.warrior@company.com",       DES_DEV,       D_ENG,       EMP_HENRY, date(1998, 3, 14), date(2024, 4,  1), 800,   0,    800,   1),
    ]

    for (
        emp_id, username, email, desig_id, dept_id,
        manager_id, dob, doj, avail, redeemed, total, version
    ) in employees:
        data = {
            "employee_id":     emp_id,
            "username":        username,
            "email":           email,
            "password_hash":   hashed,
            "designation_id":  desig_id,
            "department_id":   dept_id,
            "status_id":       S_ACTIVE,
            "date_of_joining": dt(doj),
            "date_of_birth":   dt(dob),
            "created_by":      EMP_ADMIN,
            "updated_by":      EMP_ADMIN,
            "updated_at":      NOW,
        }
        if manager_id:
            data["manager_id"] = manager_id

        await db.employees.create(data=data)
        await db.wallets.create(data={
            "employee_id":         emp_id,
            "available_points":    avail,
            "redeemed_points":     redeemed,
            "total_earned_points": total,
            "version":             version,
            "created_by":          EMP_ADMIN,
            "updated_by":          EMP_ADMIN,
            "updated_at":          NOW,
        })
        print(f"   ✅ {username:25s}  wallet: {avail:>6} pts")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# BACKFILL created_by / updated_by on early tables
# ─────────────────────────────────────────────────────────────────────────────
async def backfill_audit_fields():
    print("🔧 Backfilling created_by / updated_by on early tables...")
    for table in ["department_types", "departments", "designations"]:
        await db.execute_raw(
            f"UPDATE {table} "
            f"SET created_by = '{EMP_ADMIN}', updated_by = '{EMP_ADMIN}' "
            f"WHERE created_by IS NULL"
        )
        print(f"   ✅ {table}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEE ROLES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_employee_roles():
    print("🔐 Seeding employee_roles...")
    assignments = [
        (EMP_ADMIN,     R_SUPER_ADMIN),
        (EMP_ADMIN,     R_HR_ADMIN),
        (EMP_ADMIN,     R_AUDITOR),
        (EMP_ALICE,     R_DIRECTOR),
        (EMP_ALICE,     R_MANAGER),
        (EMP_JANE,      R_MANAGER),
        (EMP_JANE,      R_EMPLOYEE),
        (EMP_GRACE,     R_HR_ADMIN),
        (EMP_GRACE,     R_EMPLOYEE),
        (EMP_HENRY,     R_TEAM_LEAD),
        (EMP_HENRY,     R_EMPLOYEE),
        (EMP_IVY,       R_TEAM_LEAD),
        (EMP_IVY,       R_EMPLOYEE),
        (EMP_JAMES,     R_TEAM_LEAD),
        (EMP_JAMES,     R_EMPLOYEE),
        (EMP_JOHN,      R_EMPLOYEE),
        (EMP_ARIJIT,    R_EMPLOYEE),
        (EMP_SHUBRAJIT, R_EMPLOYEE),
        (EMP_PRASUN,    R_EMPLOYEE),
        (EMP_BOB,       R_EMPLOYEE),
        (EMP_CAROL,     R_EMPLOYEE),
        (EMP_DAVE,      R_EMPLOYEE),
        (EMP_EVE,       R_EMPLOYEE),
        (EMP_FRANK,     R_EMPLOYEE),
        (EMP_KATE,      R_EMPLOYEE),
        (EMP_LEO,       R_EMPLOYEE),
        (EMP_MIA,       R_EMPLOYEE),
        (EMP_NOAH,      R_EMPLOYEE),
        (EMP_OLIVIA,    R_EMPLOYEE),
        (EMP_PETER,     R_EMPLOYEE),
        (EMP_QUINN,     R_EMPLOYEE),
        (EMP_RACHEL,    R_EMPLOYEE),
        (EMP_SAM,       R_EMPLOYEE),
        (EMP_TINA,      R_EMPLOYEE),
        (EMP_UMAR,      R_EMPLOYEE),
        (EMP_VERA,      R_EMPLOYEE),
        (EMP_WILL,      R_EMPLOYEE),
        (EMP_XENA,      R_EMPLOYEE),
    ]
    for emp_id, role_id in assignments:
        await db.employee_roles.create(data={
            "employee_id": emp_id,
            "role_id":     role_id,
            "assigned_by": EMP_ADMIN,
            "is_active":   True,
            "created_by":  EMP_ADMIN,
            "updated_by":  EMP_ADMIN,
            "updated_at":  NOW,
        })
    print(f"   ✅ Seeded {len(assignments)} role assignments\n")


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_review_categories():
    print("🏷️  Seeding review_categories...")
    rows = [
        (RC_OWNERSHIP,     "OWNERSHIP",       "Ownership",        "1.2000", "Taking responsibility and driving results to completion"),
        (RC_INNOVATION,    "INNOVATION",      "Innovation",       "1.3000", "Creative thinking and novel problem solving"),
        (RC_COLLAB,        "COLLABORATION",   "Collaboration",    "1.1000", "Effective teamwork and cross-functional cooperation"),
        (RC_LEADERSHIP,    "LEADERSHIP",      "Leadership",       "1.4000", "Inspiring and guiding others toward shared goals"),
        (RC_QUALITY,       "QUALITY",         "Quality",          "1.2000", "Consistently delivering high-quality, well-tested work"),
        (RC_MENTORSHIP,    "MENTORSHIP",      "Mentorship",       "1.3000", "Actively coaching and developing other team members"),
        (RC_DELIVERY,      "DELIVERY",        "On-Time Delivery", "1.2000", "Reliably shipping work on schedule and within scope"),
        (RC_PROBLEM_SOLVE, "PROBLEM_SOLVING", "Problem Solving",  "1.3000", "Breaking down complex problems and finding effective solutions"),
        (RC_ADAPTABILITY,  "ADAPTABILITY",    "Adaptability",     "1.1000", "Embracing change and thriving in dynamic environments"),
        (RC_CUSTOMER,      "CUSTOMER_FOCUS",  "Customer Focus",   "1.2000", "Prioritising user and stakeholder needs in every decision"),
    ]
    for cat_id, code, name, mult, desc in rows:
        await db.review_categories.create(data={
            "category_id":   cat_id,
            "category_code": code,
            "category_name": name,
            "multiplier":    mult,
            "description":   desc,
            "is_active":     True,
            "created_by":    EMP_ADMIN,
            "updated_by":    EMP_ADMIN,
            "updated_at":    NOW,
        })
    print(f"   ✅ Seeded {len(rows)} review categories\n")


# ─────────────────────────────────────────────────────────────────────────────
# REWARD CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reward_categories():
    print("🏷️  Seeding reward_categories...")
    rows = [
        (RWCAT_GIFT,     "Gift Cards",  "GIFT_CARD",   "Digital and physical gift cards"),
        (RWCAT_MERCH,    "Merchandise", "MERCHANDISE", "Company branded merchandise and physical items"),
        (RWCAT_EXP,      "Experiences", "EXPERIENCE",  "Events, team outings, and experiences"),
        (RWCAT_WELLNESS, "Wellness",    "WELLNESS",    "Health, fitness, and wellbeing benefits"),
        (RWCAT_LEARNING, "Learning",    "LEARNING",    "Online courses, books, and certifications"),
    ]
    for cat_id, name, code, desc in rows:
        await db.reward_categories.create(data={
            "category_id":   cat_id,
            "category_name": name,
            "category_code": code,
            "description":   desc,
            "is_active":     True,
            "created_by":    EMP_ADMIN,
            "updated_by":    EMP_ADMIN,
            "updated_at":    NOW,
        })
    print(f"   ✅ Seeded {len(rows)} reward categories\n")


# ─────────────────────────────────────────────────────────────────────────────
# REWARD CATALOG (30 rows)
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reward_catalog():
    print("🎁 Seeding reward_catalog...")
    rows = [
        (CAT_AMZ_010, "Amazon Gift Card $10",           "REW-AMZ-010",  "Amazon digital gift card $10",              RWCAT_GIFT,     100,  100,  100,  200),
        (CAT_AMZ_025, "Amazon Gift Card $25",           "REW-AMZ-025",  "Amazon digital gift card $25",              RWCAT_GIFT,     250,  250,  250,  150),
        (CAT_AMZ_050, "Amazon Gift Card $50",           "REW-AMZ-050",  "Amazon digital gift card $50",              RWCAT_GIFT,     500,  500,  500,   80),
        (CAT_FLK_020, "Flipkart Voucher $20",           "REW-FLK-020",  "Flipkart shopping voucher $20",             RWCAT_GIFT,     200,  200,  200,  120),
        (CAT_SWG_015, "Swiggy Food Voucher $15",        "REW-SWG-015",  "Swiggy food delivery voucher $15",          RWCAT_GIFT,     150,  150,  150,  100),
        (CAT_NET_001, "Netflix 1-Month",                "REW-NET-001",  "One month Netflix subscription",            RWCAT_GIFT,     300,  300,  300,   60),
        (CAT_TSH_001, "Company T-Shirt (S/M/L/XL)",    "REW-TSH-001",  "Premium company branded T-shirt",           RWCAT_MERCH,    200,  200,  200,  250),
        (CAT_HOD_001, "Company Hoodie",                 "REW-HOD-001",  "Premium company branded hoodie",            RWCAT_MERCH,    400,  400,  400,   80),
        (CAT_CAP_001, "Company Cap",                    "REW-CAP-001",  "Embroidered company cap",                   RWCAT_MERCH,    150,  150,  150,  300),
        (CAT_MUG_001, "Company Mug",                    "REW-MUG-001",  "Ceramic company branded mug",               RWCAT_MERCH,    100,  100,  100,  400),
        (CAT_BAG_001, "Company Backpack",               "REW-BAG-001",  "Premium laptop backpack with logo",         RWCAT_MERCH,    600,  600,  600,   50),
        (CAT_BTL_001, "Company Water Bottle",           "REW-BTL-001",  "Insulated stainless steel water bottle",    RWCAT_MERCH,    250,  250,  250,  150),
        (CAT_LNC_001, "Team Lunch Voucher (5 pax)",     "REW-LNC-001",  "Lunch for you and your team (up to 5)",     RWCAT_EXP,      500,  500,  500,   30),
        (CAT_DIN_001, "Team Dinner Voucher (5 pax)",    "REW-DIN-001",  "Dinner for you and your team (up to 5)",    RWCAT_EXP,      700,  700,  700,   20),
        (CAT_MOV_001, "Movie Tickets (2 pax)",          "REW-MOV-001",  "Two premium movie tickets",                 RWCAT_EXP,      300,  300,  300,   75),
        (CAT_STA_001, "Weekend Staycation",             "REW-STA-001",  "2-night hotel staycation for 2",            RWCAT_EXP,     2000, 2000, 2000,   10),
        (CAT_SPA_001, "Spa Day Voucher",                "REW-SPA-001",  "Full-day spa session for 1",                RWCAT_EXP,      800,  800,  800,   25),
        (CAT_AMU_001, "Amusement Park Tickets",         "REW-AMU-001",  "Two tickets to a local amusement park",     RWCAT_EXP,      600,  600,  600,   40),
        (CAT_GYM_001, "Gym Membership 1 Month",         "REW-GYM-001",  "One-month gym membership at partner gyms", RWCAT_WELLNESS, 400,  400,  400,   50),
        (CAT_YOG_001, "Yoga Class Pack (10 sessions)",  "REW-YOG-001",  "10-session pack at a yoga studio",          RWCAT_WELLNESS, 350,  350,  350,   40),
        (CAT_MHT_001, "Mental Health App (1 Year)",     "REW-MHT-001",  "Annual subscription to a wellness app",     RWCAT_WELLNESS, 500,  500,  500,   60),
        (CAT_HLT_001, "Health Checkup Package",         "REW-HLT-001",  "Comprehensive annual health checkup",       RWCAT_WELLNESS, 800,  800,  800,   30),
        (CAT_ERG_001, "Ergonomic Cushion Set",          "REW-ERG-001",  "Lumbar and seat cushion for better posture",RWCAT_WELLNESS, 300,  300,  300,  100),
        (CAT_UDM_001, "Udemy Course (1 course)",        "REW-UDM-001",  "Any single Udemy course of choice",         RWCAT_LEARNING, 300,  300,  300,   80),
        (CAT_CRS_001, "Coursera 1-Month Plus",          "REW-CRS-001",  "1-month Coursera Plus subscription",        RWCAT_LEARNING, 500,  500,  500,   50),
        (CAT_ORL_001, "O'Reilly 1-Month Access",        "REW-ORL-001",  "1-month O'Reilly learning platform access", RWCAT_LEARNING, 450,  450,  450,   40),
        (CAT_BKS_030, "Tech Book Voucher $30",          "REW-BKS-030",  "$30 voucher for technical books",           RWCAT_LEARNING, 300,  300,  300,  120),
        (CAT_AWS_CPE, "AWS Cloud Practitioner Exam",    "REW-AWS-CPE",  "AWS Cloud Practitioner exam voucher",       RWCAT_LEARNING,1200, 1200, 1200,   20),
        (CAT_GCP_001, "Google Cloud Exam Voucher",      "REW-GCP-001",  "Google Cloud Professional exam voucher",    RWCAT_LEARNING,1500, 1500, 1500,   15),
        (CAT_CONF_001,"Conference Ticket",              "REW-CONF-001", "Single ticket to an industry conference",   RWCAT_LEARNING, 800,  800,  800,   25),
    ]
    for catalog_id, name, code, desc, cat_id, default_pts, min_pts, max_pts, stock in rows:
        await db.reward_catalog.create(data={
            "catalog_id":      catalog_id,
            "reward_name":     name,
            "reward_code":     code,
            "description":     desc,
            "default_points":  default_pts,
            "min_points":      min_pts,
            "max_points":      max_pts,
            "is_active":       True,
            "category_id":     cat_id,
            "available_stock": stock,
            "created_by":      EMP_ADMIN,
            "updated_by":      EMP_ADMIN,
            "updated_at":      NOW,
        })
    print(f"   ✅ Seeded {len(rows)} catalog items\n")


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS + REVIEW_CATEGORY_TAGS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reviews():
    print("⭐ Seeding reviews + review_category_tags...")
    review_data = [
        (EMP_JANE,   EMP_JOHN,      "Delivered the auth module on time with excellent test coverage.",                  17.6, 30, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),       (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_HENRY,  EMP_BOB,       "Bob consistently ships quality code with minimal review cycles.",                  15.0, 28, [(RC_QUALITY,       "1.2000", "QUALITY"),         (RC_OWNERSHIP,     "1.2000", "OWNERSHIP")]),
        (EMP_HENRY,  EMP_ARIJIT,    "Arijit showed great initiative on the caching layer refactor.",                    14.0, 25, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_PROBLEM_SOLVE, "1.3000", "PROBLEM_SOLVING")]),
        (EMP_JAMES,  EMP_SHUBRAJIT, "Reliable contributor; platform migrations were flawless.",                         13.5, 22, [(RC_DELIVERY,      "1.2000", "DELIVERY"),        (RC_QUALITY,       "1.2000", "QUALITY")]),
        (EMP_JAMES,  EMP_PRASUN,    "Prasun's documentation is exemplary and greatly helps onboarding.",                12.0, 20, [(RC_COLLAB,        "1.1000", "COLLABORATION"),   (RC_CUSTOMER,      "1.2000", "CUSTOMER_FOCUS")]),
        (EMP_IVY,    EMP_OLIVIA,    "Olivia's regression suite caught 3 critical bugs pre-release.",                    16.0, 18, [(RC_QUALITY,       "1.2000", "QUALITY"),         (RC_OWNERSHIP,     "1.2000", "OWNERSHIP")]),
        (EMP_IVY,    EMP_PETER,     "Peter automated the entire smoke test pipeline — huge time saver.",                18.0, 17, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_JANE,   EMP_CAROL,     "Carol's DevOps work reduced deployment time by 40%.",                              20.0, 16, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_PROBLEM_SOLVE, "1.3000", "PROBLEM_SOLVING")]),
        (EMP_HENRY,  EMP_DAVE,      "Dave is growing fast; great first solo feature delivery.",                          9.0, 15, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),       (RC_ADAPTABILITY,  "1.1000", "ADAPTABILITY")]),
        (EMP_HENRY,  EMP_EVE,       "Eve adapted quickly to the new CI pipeline — impressive turnaround.",              11.0, 14, [(RC_ADAPTABILITY,  "1.1000", "ADAPTABILITY"),    (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_JAMES,  EMP_FRANK,     "Frank stepped up to own the payment integration end-to-end.",                     12.0, 13, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),        (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_JAMES,  EMP_KATE,      "Kate's pull requests are thorough, well-tested, and consistently on time.",        11.0, 12, [(RC_QUALITY,       "1.2000", "QUALITY"),         (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_HENRY,  EMP_LEO,       "Leo mentored two juniors this quarter — outstanding leadership.",                  22.0, 11, [(RC_LEADERSHIP,    "1.4000", "LEADERSHIP"),      (RC_MENTORSHIP,    "1.3000", "MENTORSHIP")]),
        (EMP_JANE,   EMP_MIA,       "Mia proactively picked up the infra monitoring task nobody wanted.",               13.0, 10, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),       (RC_ADAPTABILITY,  "1.1000", "ADAPTABILITY")]),
        (EMP_HENRY,  EMP_NOAH,      "Noah joined recently but onboarded quickly — promising start.",                     8.0,  9, [(RC_ADAPTABILITY,  "1.1000", "ADAPTABILITY"),    (RC_COLLAB,        "1.1000", "COLLABORATION")]),
        (EMP_IVY,    EMP_QUINN,     "Quinn's exploratory testing found edge cases that saved a P0 incident.",           19.0,  8, [(RC_PROBLEM_SOLVE, "1.3000", "PROBLEM_SOLVING"), (RC_QUALITY,       "1.2000", "QUALITY")]),
        (EMP_GRACE,  EMP_RACHEL,    "Rachel handled the entire onboarding for 5 new hires seamlessly.",                 14.0,  7, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),       (RC_CUSTOMER,      "1.2000", "CUSTOMER_FOCUS")]),
        (EMP_GRACE,  EMP_SAM,       "Sam's employee survey analysis provided actionable insights for HR.",              13.0,  6, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_CUSTOMER,      "1.2000", "CUSTOMER_FOCUS")]),
        (EMP_ALICE,  EMP_JANE,      "Jane led the Q3 roadmap delivery end-to-end — exemplary management.",             25.0,  5, [(RC_LEADERSHIP,    "1.4000", "LEADERSHIP"),      (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_ALICE,  EMP_GRACE,     "Grace overhauled the appraisal process; measurable improvement in NPS.",          21.0,  4, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_LEADERSHIP,    "1.4000", "LEADERSHIP")]),
        (EMP_ALICE,  EMP_HENRY,     "Henry coached three junior engineers who are now team leads.",                     24.0,  3, [(RC_MENTORSHIP,    "1.3000", "MENTORSHIP"),      (RC_LEADERSHIP,    "1.4000", "LEADERSHIP")]),
        (EMP_JANE,   EMP_XENA,      "Xena delivered a well-structured feature on first attempt.",                       10.0,  2, [(RC_QUALITY,       "1.2000", "QUALITY"),         (RC_DELIVERY,      "1.2000", "DELIVERY")]),
        (EMP_TINA,   EMP_UMAR,      "Umar's financial dashboard saved hours of manual reporting each week.",            15.0,  2, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_CUSTOMER,      "1.2000", "CUSTOMER_FOCUS")]),
        (EMP_TINA,   EMP_VERA,      "Vera streamlined compliance documentation significantly.",                          12.5,  1, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),       (RC_QUALITY,       "1.2000", "QUALITY")]),
        (EMP_ALICE,  EMP_WILL,      "Will's growth campaign drove a 20% uplift in trial signups.",                     23.0,  1, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_CUSTOMER,      "1.2000", "CUSTOMER_FOCUS")]),
        (EMP_HENRY,  EMP_BOB,       "Bob's code review feedback is consistently constructive and thorough.",            13.0,  1, [(RC_COLLAB,        "1.1000", "COLLABORATION"),   (RC_MENTORSHIP,    "1.3000", "MENTORSHIP")]),
        (EMP_IVY,    EMP_OLIVIA,    "Olivia led knowledge-sharing sessions on test automation best practices.",         16.5,  0, [(RC_LEADERSHIP,    "1.4000", "LEADERSHIP"),      (RC_COLLAB,        "1.1000", "COLLABORATION")]),
        (EMP_JAMES,  EMP_PRASUN,    "Prasun proactively identified and fixed a critical security vulnerability.",       19.0,  0, [(RC_OWNERSHIP,     "1.2000", "OWNERSHIP"),       (RC_PROBLEM_SOLVE, "1.3000", "PROBLEM_SOLVING")]),
        (EMP_GRACE,  EMP_RACHEL,    "Rachel resolved a sensitive employee dispute professionally and empathetically.",  14.5,  0, [(RC_LEADERSHIP,    "1.4000", "LEADERSHIP"),      (RC_CUSTOMER,      "1.2000", "CUSTOMER_FOCUS")]),
        (EMP_JANE,   EMP_CAROL,     "Carol implemented zero-downtime deployments for the entire platform.",             21.0,  0, [(RC_INNOVATION,    "1.3000", "INNOVATION"),      (RC_DELIVERY,      "1.2000", "DELIVERY")]),
    ]

    tag_count = 0
    for reviewer_id, receiver_id, comment, raw_pts, days_ago, tags in review_data:
        review_id = uid()
        await db.reviews.create(data={
            "review_id":   review_id,
            "reviewer_id": reviewer_id,
            "receiver_id": receiver_id,
            "comment":     comment,
            "status_id":   S_REV_ACTIVE,
            "raw_points":  raw_pts,
            "review_at":   NOW - timedelta(days=days_ago),
            "created_by":  reviewer_id,
            "updated_by":  reviewer_id,
            "updated_at":  NOW,
        })
        for cat_id, mult, code in tags:
            await db.review_category_tags.create(data={
                "review_id":              review_id,
                "category_id":            cat_id,
                "multiplier_snapshot":    mult,
                "category_code_snapshot": code,
            })
            tag_count += 1
    print(f"   ✅ Seeded {len(review_data)} reviews with {tag_count} category tags\n")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_transactions():
    print("💰 Seeding transactions...")

    wallet_map = {}
    for emp_id in [
        EMP_JOHN, EMP_ARIJIT, EMP_SHUBRAJIT, EMP_PRASUN, EMP_BOB, EMP_CAROL,
        EMP_DAVE, EMP_EVE, EMP_FRANK, EMP_KATE, EMP_LEO, EMP_MIA, EMP_NOAH,
        EMP_OLIVIA, EMP_PETER, EMP_QUINN, EMP_RACHEL, EMP_SAM,
        EMP_HENRY, EMP_IVY, EMP_JAMES, EMP_JANE, EMP_ALICE, EMP_GRACE,
        EMP_TINA, EMP_UMAR, EMP_VERA, EMP_WILL, EMP_XENA,
    ]:
        w = await db.wallets.find_unique(where={"employee_id": emp_id})
        wallet_map[emp_id] = w.wallet_id

    txns = [
        (EMP_JOHN,      200,  TT_CREDIT,     S_TXN_APPROVED, "Q1 performance review credit",                "TXN-2025-001", 90),
        (EMP_JOHN,      300,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-002", 60),
        (EMP_JOHN,      500,  TT_REDEMPTION, S_TXN_APPROVED, "Redemption: Company Hoodie",                  "TXN-2025-003", 30),
        (EMP_ARIJIT,    250,  TT_CREDIT,     S_TXN_APPROVED, "Q1 performance review credit",                "TXN-2025-004", 85),
        (EMP_ARIJIT,    400,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: caching layer refactor",          "TXN-2025-005", 25),
        (EMP_SHUBRAJIT, 300,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-006", 55),
        (EMP_PRASUN,    350,  TT_CREDIT,     S_TXN_APPROVED, "Q1 performance review credit",                "TXN-2025-007", 80),
        (EMP_PRASUN,    500,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: security vulnerability fix",      "TXN-2025-008",  5),
        (EMP_BOB,       300,  TT_CREDIT,     S_TXN_APPROVED, "Q1 performance review credit",                "TXN-2025-009", 88),
        (EMP_BOB,       200,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-010", 50),
        (EMP_BOB,       400,  TT_REDEMPTION, S_TXN_APPROVED, "Redemption: Team Lunch Voucher",              "TXN-2025-011", 20),
        (EMP_CAROL,     500,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: zero-downtime deployment",        "TXN-2025-012", 10),
        (EMP_CAROL,     300,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-013", 45),
        (EMP_DAVE,      150,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-014", 55),
        (EMP_LEO,       200,  TT_CREDIT,     S_TXN_APPROVED, "Q1 performance review credit",                "TXN-2025-015", 92),
        (EMP_LEO,       350,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: mentoring two engineers",         "TXN-2025-016", 15),
        (EMP_LEO,       300,  TT_REDEMPTION, S_TXN_APPROVED, "Redemption: Udemy Course",                    "TXN-2025-017",  8),
        (EMP_OLIVIA,    250,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-018", 40),
        (EMP_OLIVIA,    300,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: caught critical regression bugs", "TXN-2025-019", 12),
        (EMP_PETER,     400,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: automated smoke test pipeline",   "TXN-2025-020", 18),
        (EMP_PETER,     300,  TT_REDEMPTION, S_TXN_APPROVED, "Redemption: Netflix 1-Month",                 "TXN-2025-021", 10),
        (EMP_QUINN,     350,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-022", 35),
        (EMP_RACHEL,    200,  TT_CREDIT,     S_TXN_APPROVED, "Q1 performance review credit",                "TXN-2025-023", 82),
        (EMP_SAM,       200,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-024", 52),
        (EMP_HENRY,     500,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: coaching 3 engineers to TL",      "TXN-2025-025",  7),
        (EMP_JANE,      600,  TT_CREDIT,     S_TXN_APPROVED, "Q1 leadership performance credit",            "TXN-2025-026", 95),
        (EMP_WILL,      450,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: 20% uplift in trial signups",     "TXN-2025-027",  3),
        (EMP_TINA,      350,  TT_CREDIT,     S_TXN_APPROVED, "Q2 performance review credit",                "TXN-2025-028", 48),
        (EMP_EVE,       100,  TT_ADJUSTMENT, S_TXN_APPROVED, "Manual adjustment: corrected wallet error",   "TXN-2025-029",  5),
        (EMP_FRANK,     200,  TT_BONUS,      S_TXN_APPROVED, "Spot bonus: payment integration ownership",   "TXN-2025-030", 14),
    ]

    for emp_id, amount, type_id, status_id, desc, ref, days_ago in txns:
        await db.transactions.create(data={
            "wallet_id":           wallet_map[emp_id],
            "amount":              amount,
            "transaction_type_id": type_id,
            "status_id":           status_id,
            "description":         desc,
            "reference_number":    ref,
            "transaction_at":      NOW - timedelta(days=days_ago),
            "created_by":          emp_id,
            "updated_by":          emp_id,
            "updated_at":          NOW,
        })
    print(f"   ✅ Seeded {len(txns)} transactions\n")


# ─────────────────────────────────────────────────────────────────────────────
# REWARD HISTORY
# ─────────────────────────────────────────────────────────────────────────────
async def seed_reward_history():
    print("🎀 Seeding reward_history...")

    wallet_map = {}
    for emp_id in [
        EMP_JOHN, EMP_ARIJIT, EMP_BOB, EMP_CAROL, EMP_LEO, EMP_OLIVIA,
        EMP_PETER, EMP_QUINN, EMP_HENRY, EMP_JAMES, EMP_JANE, EMP_GRACE,
        EMP_PRASUN, EMP_SHUBRAJIT, EMP_RACHEL, EMP_SAM, EMP_DAVE,
        EMP_FRANK, EMP_KATE, EMP_ALICE, EMP_TINA, EMP_UMAR, EMP_WILL,
        EMP_NOAH, EMP_MIA, EMP_EVE, EMP_IVY, EMP_XENA, EMP_VERA, EMP_ADMIN,
    ]:
        w = await db.wallets.find_unique(where={"employee_id": emp_id})
        wallet_map[emp_id] = w.wallet_id

    history_data = [
        (EMP_JOHN,      CAT_HOD_001,  400,  "End-of-year hoodie redemption",               30),
        (EMP_JOHN,      CAT_AMZ_025,  250,  "Redeemed Amazon gift card",                   15),
        (EMP_ARIJIT,    CAT_UDM_001,  300,  "Redeemed Udemy course on system design",      25),
        (EMP_SHUBRAJIT, CAT_AMZ_010,  100,  "Redeemed small Amazon gift card",             20),
        (EMP_PRASUN,    CAT_CRS_001,  500,  "Redeemed Coursera Plus for 1 month",           5),
        (EMP_BOB,       CAT_LNC_001,  500,  "Team lunch for sprint completion",            20),
        (EMP_BOB,       CAT_TSH_001,  200,  "Company T-shirt redemption",                 10),
        (EMP_CAROL,     CAT_GYM_001,  400,  "Gym membership for health month",             8),
        (EMP_CAROL,     CAT_AWS_CPE, 1200,  "AWS Cloud Practitioner exam voucher",          3),
        (EMP_LEO,       CAT_UDM_001,  300,  "Udemy course on leadership",                  8),
        (EMP_LEO,       CAT_MOV_001,  300,  "Movie tickets with family",                   4),
        (EMP_OLIVIA,    CAT_YOG_001,  350,  "Yoga class pack for wellness",               12),
        (EMP_PETER,     CAT_NET_001,  300,  "Netflix subscription redemption",            10),
        (EMP_QUINN,     CAT_FLK_020,  200,  "Flipkart voucher redeemed",                   6),
        (EMP_HENRY,     CAT_DIN_001,  700,  "Team dinner for exceeding Q2 goals",          7),
        (EMP_HENRY,     CAT_GCP_001, 1500,  "Google Cloud exam voucher",                   2),
        (EMP_JANE,      CAT_STA_001, 2000,  "Weekend staycation reward",                   5),
        (EMP_GRACE,     CAT_SPA_001,  800,  "Spa day wellness reward",                     9),
        (EMP_JAMES,     CAT_CONF_001, 800,  "Industry conference ticket",                  4),
        (EMP_RACHEL,    CAT_MHT_001,  500,  "Mental health app subscription",              3),
        (EMP_SAM,       CAT_BKS_030,  300,  "Technical books voucher",                     7),
        (EMP_DAVE,      CAT_MUG_001,  100,  "Company mug for desk",                       14),
        (EMP_KATE,      CAT_CAP_001,  150,  "Company branded cap",                        10),
        (EMP_TINA,      CAT_ORL_001,  450,  "O'Reilly 1-month access for ops reading",     5),
        (EMP_UMAR,      CAT_AMZ_050,  500,  "Amazon gift card $50",                        8),
        (EMP_WILL,      CAT_AMU_001,  600,  "Amusement park tickets with family",          3),
        (EMP_ALICE,     CAT_DIN_001,  700,  "Director team dinner",                        6),
        (EMP_IVY,       CAT_HLT_001,  800,  "Annual health checkup",                       4),
        (EMP_XENA,      CAT_SWG_015,  150,  "Swiggy voucher for late-night coding",        2),
        (EMP_VERA,      CAT_ERG_001,  300,  "Ergonomic cushion set for home office",       5),
    ]

    for emp_id, catalog_id, points, comment, days_ago in history_data:
        await db.reward_history.create(data={
            "wallet_id":  wallet_map[emp_id],
            "catalog_id": catalog_id,
            "granted_by": EMP_ADMIN,
            "points":     points,
            "comment":    comment,
            "granted_at": NOW - timedelta(days=days_ago),
            "created_by": emp_id,
            "updated_by": emp_id,
            "updated_at": NOW,
        })
    print(f"   ✅ Seeded {len(history_data)} reward history entries\n")


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────
async def seed_notifications():
    print("🔔 Seeding notifications...")
    notifs = [
        (EMP_JOHN,      "Points Credited",         "You received 200 points for Q1 performance review.",            "CREDIT",     True,  True,  1, 90),
        (EMP_JOHN,      "Reward Redeemed",          "Your Company Hoodie redemption has been approved.",             "REDEMPTION", True,  True,  1, 30),
        (EMP_ARIJIT,    "Points Credited",          "You received 250 points for Q1 performance review.",            "CREDIT",     True,  True,  1, 85),
        (EMP_ARIJIT,    "Bonus Points Awarded",     "You received a 400-point spot bonus for the caching refactor.", "BONUS",      False, True,  1, 25),
        (EMP_SHUBRAJIT, "Points Credited",          "You received 300 points for Q2 performance review.",            "CREDIT",     True,  True,  1, 55),
        (EMP_PRASUN,    "Spot Bonus",               "You received a 500-point bonus for fixing a security issue.",   "BONUS",      False, True,  1,  5),
        (EMP_BOB,       "Team Lunch Redeemed",      "Your Team Lunch Voucher has been processed.",                   "REDEMPTION", True,  True,  1, 20),
        (EMP_CAROL,     "Exam Voucher Ready",       "Your AWS Cloud Practitioner voucher has been issued.",          "REDEMPTION", False, True,  1,  3),
        (EMP_LEO,       "Leadership Bonus",         "500 points awarded for mentoring three engineers.",             "BONUS",      True,  True,  1, 15),
        (EMP_LEO,       "Reward Redeemed",          "Your Udemy course redemption is complete.",                     "REDEMPTION", True,  True,  1,  8),
        (EMP_OLIVIA,    "Great Review Received",    "You received a positive review from your team lead.",           "REVIEW",     True,  True,  1, 12),
        (EMP_PETER,     "Automation Bonus",         "400 bonus points for automating the smoke test pipeline.",      "BONUS",      True,  True,  1, 18),
        (EMP_HENRY,     "Team Dinner Approved",     "Your team dinner voucher redemption is approved.",              "REDEMPTION", True,  True,  1,  7),
        (EMP_JANE,      "Staycation Approved",      "Your weekend staycation reward has been processed.",            "REDEMPTION", True,  True,  1,  5),
        (EMP_GRACE,     "Spa Day Confirmed",        "Your spa day reward has been confirmed.",                       "REDEMPTION", True,  True,  1,  9),
        (EMP_QUINN,     "Points Credited",          "You received 350 points for Q2 performance review.",            "CREDIT",     True,  True,  1, 35),
        (EMP_RACHEL,    "Mental Health App Ready",  "Your annual mental health app subscription is active.",         "REDEMPTION", False, True,  1,  3),
        (EMP_SAM,       "Book Voucher Issued",      "Your $30 technical books voucher has been issued.",             "REDEMPTION", True,  True,  1,  7),
        (EMP_WILL,      "Campaign Bonus",           "450 points for driving 20% uplift in trial signups.",           "BONUS",      False, False, 0,  3),
        (EMP_TINA,      "Points Credited",          "You received 350 points for Q2 performance review.",            "CREDIT",     False, False, 0, 48),
        (EMP_UMAR,      "Gift Card Issued",         "Your Amazon $50 gift card has been issued.",                    "REDEMPTION", False, True,  1,  8),
        (EMP_ALICE,     "Director Bonus Processed", "Team dinner voucher for quarterly milestones approved.",        "REDEMPTION", True,  True,  1,  6),
        (EMP_FRANK,     "Bonus Points Awarded",     "200 bonus points for owning the payment integration.",          "BONUS",      False, False, 0, 14),
        (EMP_EVE,       "Wallet Adjusted",          "Your wallet balance was adjusted by 100 points.",               "REWARD",     False, False, 0,  5),
        (EMP_DAVE,      "Company Mug Dispatched",   "Your company mug has been dispatched.",                         "REDEMPTION", True,  True,  1, 14),
        (EMP_KATE,      "Company Cap Ready",        "Your branded company cap has been processed.",                  "REDEMPTION", True,  True,  1, 10),
        (EMP_IVY,       "Health Checkup Scheduled", "Your annual health checkup has been scheduled.",                "REDEMPTION", False, True,  1,  4),
        (EMP_XENA,      "First Review Received",    "You just received your first peer review — great start!",       "REVIEW",     False, False, 0,  2),
        (EMP_VERA,      "Ergonomic Set Dispatched", "Your ergonomic cushion set has been shipped.",                  "REDEMPTION", False, True,  1,  5),
        (EMP_NOAH,      "Welcome Bonus",            "Welcome! 100 onboarding bonus points have been credited.",      "BONUS",      False, False, 0,  1),
    ]
    for emp_id, title, message, ntype, is_read, email_sent, send_attempts, days_ago in notifs:
        read_at = (NOW - timedelta(days=days_ago // 2)) if is_read else None
        data = {
            "employee_id":   emp_id,
            "title":         title,
            "message":       message,
            "type":          ntype,
            "is_read":       is_read,
            "email_sent":    email_sent,
            "send_attempts": send_attempts,
            "created_at":    NOW - timedelta(days=days_ago),
        }
        if read_at:
            data["read_at"] = read_at
        await db.notifications.create(data=data)
    print(f"   ✅ Seeded {len(notifs)} notifications\n")


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────────
async def seed_audit_log():
    print("📝 Seeding audit_log...")
    entries = [
        ("employees",         EMP_JOHN,       "INSERT", None,                                        {"username": "john.doe", "status": "ACTIVE"},                                EMP_ADMIN),
        ("employees",         EMP_ARIJIT,     "INSERT", None,                                        {"username": "arijit.banik", "status": "ACTIVE"},                            EMP_ADMIN),
        ("employees",         EMP_SHUBRAJIT,  "INSERT", None,                                        {"username": "shubrajit.deb", "status": "ACTIVE"},                           EMP_ADMIN),
        ("employees",         EMP_PRASUN,     "INSERT", None,                                        {"username": "prasun.chakraborty", "status": "ACTIVE"},                      EMP_ADMIN),
        ("employees",         EMP_BOB,        "INSERT", None,                                        {"username": "midanka.lahon", "status": "ACTIVE"},                           EMP_ADMIN),
        ("employees",         EMP_CAROL,      "INSERT", None,                                        {"username": "swarup.das", "status": "ACTIVE"},                              EMP_ADMIN),
        ("employees",         EMP_EVE,        "UPDATE", {"status": "ACTIVE"},                        {"status": "INACTIVE"},                                                      EMP_ADMIN),
        ("employees",         EMP_EVE,        "UPDATE", {"status": "INACTIVE"},                      {"status": "ACTIVE"},                                                        EMP_ADMIN),
        ("wallets",           EMP_JOHN,       "UPDATE", {"available_points": 1700},                  {"available_points": 1500},                                                  EMP_ADMIN),
        ("wallets",           EMP_BOB,        "UPDATE", {"available_points": 3700},                  {"available_points": 3500},                                                  EMP_ADMIN),
        ("wallets",           EMP_LEO,        "UPDATE", {"available_points": 2200},                  {"available_points": 2000},                                                  EMP_ADMIN),
        ("reviews",           uid(),          "INSERT", None,                                        {"reviewer": "jane.smith", "receiver": "john.doe"},                         EMP_JANE),
        ("reviews",           uid(),          "INSERT", None,                                        {"reviewer": "henry.ford", "receiver": "midanka.lahon"},                    EMP_HENRY),
        ("reviews",           uid(),          "INSERT", None,                                        {"reviewer": "ivy.league", "receiver": "gautam.hazarika"},                  EMP_IVY),
        ("reviews",           uid(),          "UPDATE", {"status": "REVIEW_ACTIVE"},                 {"status": "REVIEW_DELETED"},                                                EMP_ADMIN),
        ("employee_roles",    EMP_HENRY,      "INSERT", None,                                        {"role": "TEAM_LEAD", "assigned_by": "admin.user"},                         EMP_ADMIN),
        ("employee_roles",    EMP_IVY,        "INSERT", None,                                        {"role": "TEAM_LEAD", "assigned_by": "admin.user"},                         EMP_ADMIN),
        ("reward_catalog",    CAT_AWS_CPE,    "INSERT", None,                                        {"reward_name": "AWS Cloud Practitioner Exam", "points": 1200},              EMP_ADMIN),
        ("reward_catalog",    CAT_GCP_001,    "UPDATE", {"available_stock": 20},                     {"available_stock": 15},                                                     EMP_ADMIN),
        ("reward_catalog",    CAT_STA_001,    "UPDATE", {"is_active": True},                         {"is_active": False},                                                        EMP_ADMIN),
        ("transactions",      uid(),          "INSERT", None,                                        {"amount": 500, "type": "BONUS", "employee": "swarup.das"},                  EMP_ADMIN),
        ("transactions",      uid(),          "INSERT", None,                                        {"amount": 200, "type": "BONUS", "employee": "mrinmoy.kashyap"},             EMP_ADMIN),
        ("transactions",      uid(),          "UPDATE", {"status": "PENDING"},                       {"status": "APPROVED"},                                                      EMP_ADMIN),
        ("departments",       D_ENG,          "UPDATE", {"department_name": "Software Engineering"}, {"department_name": "Engineering"},                                          EMP_ADMIN),
        ("designations",      DES_SR_DEV,     "UPDATE", {"level": 3},                                {"level": 4},                                                                EMP_ADMIN),
        ("review_categories", RC_OWNERSHIP,   "UPDATE", {"multiplier": "1.1000"},                    {"multiplier": "1.2000"},                                                    EMP_ADMIN),
        ("review_categories", RC_INNOVATION,  "UPDATE", {"multiplier": "1.2000"},                    {"multiplier": "1.3000"},                                                    EMP_ADMIN),
        ("reward_history",    uid(),          "INSERT", None,                                        {"reward": "Company Hoodie", "points": 400, "employee": "john.doe"},         EMP_ADMIN),
        ("reward_history",    uid(),          "INSERT", None,                                        {"reward": "AWS exam voucher", "points": 1200, "employee": "swarup.das"},    EMP_ADMIN),
        ("employees",         EMP_XENA,       "INSERT", None,                                        {"username": "xena.warrior", "status": "ACTIVE"},                            EMP_ADMIN),
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
                '127.0.0.1', 'seed-script/2.0', NOW()
            )
        """)
    print(f"   ✅ Seeded {len(entries)} audit log entries\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    await db.connect()
    try:
        print("=" * 70)
        print("🌱  EMPLOYEE REWARDS SYSTEM — DATABASE SEED")
        print("=" * 70)
        print()

        await clean_db()

        await seed_status_master()        # MUST be first — employees FK depends on it
        await seed_transaction_types()
        await seed_roles()
        await seed_department_types()
        await seed_departments()          # Migration needs at least 1 dept after this
        await seed_designations()         # Migration needs at least 1 desig after this
        await seed_admin_employee()
        await seed_employees()
        await backfill_audit_fields()
        await seed_employee_roles()
        await seed_review_categories()
        await seed_reward_categories()
        await seed_reward_catalog()
        await seed_reviews()
        await seed_transactions()
        await seed_reward_history()
        await seed_notifications()
        await seed_audit_log()

        print("=" * 70)
        print("🎉  SEED COMPLETE!")
        print("=" * 70)
        print()
        print("NEXT STEP:")
        print("   prisma migrate deploy")
        print("   ↳ Creates the system sentinel employee (00000000-...)")
        print("   ↳ Attaches audit triggers to all 17 tables")
        print("   ↳ Revokes UPDATE/DELETE on audit_log from the app user")
        print()
        print("📝 Login credentials (password for all: Password123!)")
        print()
        print(f"   {'username':<30} {'role(s)'}")
        print(f"   {'-'*30} {'-'*30}")
        print(f"   {'admin.user':<30} SUPER_ADMIN, HR_ADMIN, AUDITOR")
        print(f"   {'alice.wong':<30} DIRECTOR, MANAGER")
        print(f"   {'jane.smith':<30} MANAGER, EMPLOYEE")
        print(f"   {'grace.hopper':<30} HR_ADMIN, EMPLOYEE")
        print(f"   {'henry.ford':<30} TEAM_LEAD, EMPLOYEE")
        print(f"   {'ivy.league':<30} TEAM_LEAD, EMPLOYEE")
        print(f"   {'james.bond':<30} TEAM_LEAD, EMPLOYEE")
        print(f"   {'john.doe':<30} EMPLOYEE")
        print(f"   {'arijit.banik':<30} EMPLOYEE  (arijitb017@gmail.com)")
        print(f"   {'shubrajit.deb':<30} EMPLOYEE  (shubrajitdeb180603@gmail.com)")
        print(f"   {'prasun.chakraborty':<30} EMPLOYEE  (nothingshere21@gmail.com)")
        print(f"   {'... + 19 more employees':<30} EMPLOYEE")
        print()
        print(f"   password (all): {TEST_PASSWORD}")
        print()
        print("⚠️  route_permissions is EMPTY — auto-populated on microservice startup.")
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