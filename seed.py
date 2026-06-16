"""
seed.py
Full seed for rnr_db / test_db.

Run with:
    python seed.py

Requires:
    pip install prisma bcrypt python-dotenv

Strategy: find_first -> create (skip if exists) for all tables.
This avoids upsert FieldNotFoundError and UniqueViolation issues on re-runs.
"""

import asyncio
from datetime import datetime
from dotenv import load_dotenv
import bcrypt

from prisma import Prisma

load_dotenv()

HASH = bcrypt.hashpw(b"Password@123", bcrypt.gensalt()).decode()
NOW  = datetime.utcnow()


async def get_or_create(find_coro, create_coro):
    """Find existing record or create new one. Returns the record."""
    existing = await find_coro
    if existing:
        return existing
    return await create_coro


async def main():
    db = Prisma()
    await db.connect()

    print("Seeding database...")

    # =========================================================================
    # 1. STATUS MASTER
    # =========================================================================
    print("  -> status_master")

    statuses = [
        {"code": "EMP_ACTIVE",     "name": "Active",      "entity": "employee",    "desc": "Employee is active"},
        {"code": "EMP_INACTIVE",   "name": "Inactive",    "entity": "employee",    "desc": "Employee is inactive"},
        {"code": "EMP_ON_LEAVE",   "name": "On Leave",    "entity": "employee",    "desc": "Employee is on leave"},
        {"code": "EMP_TERMINATED", "name": "Terminated",  "entity": "employee",    "desc": "Employee has been terminated"},
        {"code": "EMP_PROBATION",  "name": "Probation",   "entity": "employee",    "desc": "Employee is on probation"},
        {"code": "REV_PENDING",    "name": "Pending",     "entity": "review",      "desc": "Review is pending approval"},
        {"code": "REV_APPROVED",   "name": "Approved",    "entity": "review",      "desc": "Review has been approved"},
        {"code": "REV_REJECTED",   "name": "Rejected",    "entity": "review",      "desc": "Review has been rejected"},
        {"code": "REV_DRAFT",      "name": "Draft",       "entity": "review",      "desc": "Review is in draft state"},
        {"code": "REV_WITHDRAWN",  "name": "Withdrawn",   "entity": "review",      "desc": "Review has been withdrawn"},
        {"code": "TXN_PENDING",    "name": "Pending",     "entity": "transaction", "desc": "Transaction is pending"},
        {"code": "TXN_COMPLETED",  "name": "Completed",   "entity": "transaction", "desc": "Transaction completed"},
        {"code": "TXN_FAILED",     "name": "Failed",      "entity": "transaction", "desc": "Transaction failed"},
        {"code": "TXN_REVERSED",   "name": "Reversed",    "entity": "transaction", "desc": "Transaction reversed"},
        {"code": "TXN_PROCESSING", "name": "Processing",  "entity": "transaction", "desc": "Transaction is processing"},
        {"code": "RWD_AVAILABLE",  "name": "Available",   "entity": "reward",      "desc": "Reward is available"},
        {"code": "RWD_REDEEMED",   "name": "Redeemed",    "entity": "reward",      "desc": "Reward has been redeemed"},
        {"code": "RWD_EXPIRED",    "name": "Expired",     "entity": "reward",      "desc": "Reward has expired"},
        {"code": "RWD_RESERVED",   "name": "Reserved",    "entity": "reward",      "desc": "Reward is reserved"},
        {"code": "RWD_CANCELLED",  "name": "Cancelled",   "entity": "reward",      "desc": "Reward was cancelled"},
        {"code": "ROLE_ACTIVE",    "name": "Active",      "entity": "role",        "desc": "Role is active"},
        {"code": "ROLE_INACTIVE",  "name": "Inactive",    "entity": "role",        "desc": "Role is inactive"},
        {"code": "GEN_ACTIVE",     "name": "Active",      "entity": "general",     "desc": "Record is active"},
        {"code": "GEN_INACTIVE",   "name": "Inactive",    "entity": "general",     "desc": "Record is inactive"},
        {"code": "GEN_ARCHIVED",   "name": "Archived",    "entity": "general",     "desc": "Record has been archived"},
        {"code": "GEN_DELETED",    "name": "Deleted",     "entity": "general",     "desc": "Record has been soft deleted"},
        {"code": "GEN_DRAFT",      "name": "Draft",       "entity": "general",     "desc": "Record is in draft"},
        {"code": "GEN_PUBLISHED",  "name": "Published",   "entity": "general",     "desc": "Record has been published"},
        {"code": "GEN_SUSPENDED",  "name": "Suspended",   "entity": "general",     "desc": "Record is suspended"},
        {"code": "GEN_PENDING",    "name": "Pending",     "entity": "general",     "desc": "Record is pending"},
    ]

    for s in statuses:
        if not await db.status_master.find_first(where={"status_code": s["code"]}):
            await db.status_master.create(data={
                "status_code": s["code"],
                "status_name": s["name"],
                "entity_type": s["entity"],
                "description": s["desc"],
                "updated_at":  NOW,
            })

    emp_active_status = await db.status_master.find_first(where={"status_code": "EMP_ACTIVE"})
    rev_approved      = await db.status_master.find_first(where={"status_code": "REV_APPROVED"})
    txn_completed     = await db.status_master.find_first(where={"status_code": "TXN_COMPLETED"})

    # =========================================================================
    # 2. DEPARTMENT TYPES
    # =========================================================================
    print("  -> department_types")

    dept_type_data = [
        {"name": "Engineering",    "code": "ENG"},
        {"name": "Business",       "code": "BIZ"},
        {"name": "Operations",     "code": "OPS"},
        {"name": "Support",        "code": "SUP"},
        {"name": "Executive",      "code": "EXEC"},
        {"name": "Research",       "code": "RES"},
        {"name": "Creative",       "code": "CRE"},
        {"name": "Compliance",     "code": "COMP"},
        {"name": "Infrastructure", "code": "INFRA"},
        {"name": "Analytics",      "code": "ANLT"},
    ]

    for dt in dept_type_data:
        if not await db.department_types.find_first(where={"type_code": dt["code"]}):
            await db.department_types.create(data={
                "type_name":  dt["name"],
                "type_code":  dt["code"],
                "updated_at": NOW,
            })

    dept_types = await db.department_types.find_many()
    dt_map     = {d.type_code: d.department_type_id for d in dept_types}

    # =========================================================================
    # 3. DEPARTMENTS
    # =========================================================================
    print("  -> departments")

    dept_data = [
        {"name": "Backend Engineering",      "code": "BE",     "type_code": "ENG"},
        {"name": "Frontend Engineering",     "code": "FE",     "type_code": "ENG"},
        {"name": "DevOps & Infrastructure",  "code": "DEVOPS", "type_code": "INFRA"},
        {"name": "Product Management",       "code": "PM",     "type_code": "BIZ"},
        {"name": "Human Resources",          "code": "HR",     "type_code": "OPS"},
        {"name": "Finance & Accounting",     "code": "FIN",    "type_code": "BIZ"},
        {"name": "Quality Assurance",        "code": "QA",     "type_code": "ENG"},
        {"name": "Customer Success",         "code": "CS",     "type_code": "SUP"},
        {"name": "Data & Analytics",         "code": "DA",     "type_code": "ANLT"},
        {"name": "Executive Leadership",     "code": "EL",     "type_code": "EXEC"},
        {"name": "Security",                 "code": "SEC",    "type_code": "COMP"},
        {"name": "Mobile Engineering",       "code": "MOB",    "type_code": "ENG"},
        {"name": "Design & UX",             "code": "DES",    "type_code": "CRE"},
        {"name": "Research & Development",   "code": "RD",     "type_code": "RES"},
        {"name": "Marketing",                "code": "MKT",    "type_code": "BIZ"},
        {"name": "Legal & Compliance",       "code": "LEG",    "type_code": "COMP"},
        {"name": "Sales",                    "code": "SAL",    "type_code": "BIZ"},
        {"name": "IT Support",               "code": "ITS",    "type_code": "SUP"},
        {"name": "Business Intelligence",    "code": "BI",     "type_code": "ANLT"},
        {"name": "Platform Engineering",     "code": "PLE",    "type_code": "ENG"},
        {"name": "Procurement",              "code": "PROC",   "type_code": "OPS"},
        {"name": "Training & Development",   "code": "TD",     "type_code": "OPS"},
        {"name": "Risk Management",          "code": "RM",     "type_code": "COMP"},
        {"name": "Corporate Communications", "code": "CC",     "type_code": "BIZ"},
        {"name": "Internal Audit",           "code": "IA",     "type_code": "COMP"},
        {"name": "Cloud Architecture",       "code": "CA",     "type_code": "INFRA"},
        {"name": "AI & Machine Learning",    "code": "AI",     "type_code": "RES"},
        {"name": "Technical Writing",        "code": "TW",     "type_code": "CRE"},
        {"name": "Partner Engineering",      "code": "PE",     "type_code": "ENG"},
        {"name": "Customer Experience",      "code": "CX",     "type_code": "SUP"},
    ]

    for d in dept_data:
        by_code = await db.departments.find_first(where={"department_code": d["code"]})
        by_name = await db.departments.find_first(where={"department_name": d["name"]})
        if not by_code and not by_name:
            await db.departments.create(data={
                "department_name":    d["name"],
                "department_code":    d["code"],
                "department_type_id": dt_map[d["type_code"]],
                "updated_at":         NOW,
            })

    depts    = await db.departments.find_many()
    dept_map = {d.department_code: d.department_id for d in depts}

    # =========================================================================
    # 4. DESIGNATIONS
    # =========================================================================
    print("  -> designations")

    designation_data = [
        {"name": "Chief Executive Officer",  "code": "CEO",    "level": 1},
        {"name": "Chief Technology Officer", "code": "CTO",    "level": 2},
        {"name": "Chief Financial Officer",  "code": "CFO",    "level": 2},
        {"name": "Vice President",           "code": "VP",     "level": 3},
        {"name": "Senior Director",          "code": "SDIR",   "level": 4},
        {"name": "Director",                 "code": "DIR",    "level": 5},
        {"name": "Senior Manager",           "code": "SMGR",   "level": 6},
        {"name": "Manager",                  "code": "MGR",    "level": 7},
        {"name": "Senior Engineer",          "code": "SENG",   "level": 8},
        {"name": "Engineer",                 "code": "ENG",    "level": 9},
        {"name": "Junior Engineer",          "code": "JENG",   "level": 10},
        {"name": "Principal Architect",      "code": "PARC",   "level": 4},
        {"name": "Senior Architect",         "code": "SARC",   "level": 5},
        {"name": "Lead Engineer",            "code": "LENG",   "level": 7},
        {"name": "Staff Engineer",           "code": "STENG",  "level": 6},
        {"name": "Senior Analyst",           "code": "SANA",   "level": 8},
        {"name": "Analyst",                  "code": "ANA",    "level": 9},
        {"name": "Senior Consultant",        "code": "SCON",   "level": 7},
        {"name": "Consultant",               "code": "CON",    "level": 8},
        {"name": "Associate",                "code": "ASSOC",  "level": 10},
        {"name": "Senior Associate",         "code": "SASSOC", "level": 9},
        {"name": "Specialist",               "code": "SPEC",   "level": 8},
        {"name": "Senior Specialist",        "code": "SSPEC",  "level": 7},
        {"name": "Team Lead",                "code": "TL",     "level": 7},
        {"name": "Product Manager",          "code": "PMGR",   "level": 7},
        {"name": "Senior Product Manager",   "code": "SPMGR",  "level": 6},
        {"name": "Intern",                   "code": "INT",    "level": 11},
        {"name": "Trainee",                  "code": "TRN",    "level": 11},
        {"name": "Head of Department",       "code": "HOD",    "level": 5},
        {"name": "Executive Assistant",      "code": "EA",     "level": 9},
    ]

    for d in designation_data:
        if not await db.designations.find_first(where={"designation_code": d["code"]}):
            await db.designations.create(data={
                "designation_name": d["name"],
                "designation_code": d["code"],
                "level":            d["level"],
                "is_active":        True,
                "updated_at":       NOW,
            })

    designations = await db.designations.find_many()
    desig_map    = {d.designation_code: d.designation_id for d in designations}

    # =========================================================================
    # 5. ROLES
    # =========================================================================
    print("  -> roles")

    role_data = [
        {"name": "Super Admin",      "code": "SUPER_ADMIN",   "desc": "Full system access",                   "weight": 2.0},
        {"name": "Admin",            "code": "ADMIN",         "desc": "Administrative access",                "weight": 1.8},
        {"name": "HR Manager",       "code": "HR_MANAGER",    "desc": "HR management access",                 "weight": 1.5},
        {"name": "Manager",          "code": "MANAGER",       "desc": "Team manager access",                  "weight": 1.4},
        {"name": "Senior Employee",  "code": "SENIOR_EMP",    "desc": "Senior employee access",               "weight": 1.2},
        {"name": "Employee",         "code": "EMPLOYEE",      "desc": "Standard employee access",             "weight": 1.0},
        {"name": "Reviewer",         "code": "REVIEWER",      "desc": "Can submit reviews",                   "weight": 1.3},
        {"name": "Finance",          "code": "FINANCE",       "desc": "Finance team access",                  "weight": 1.2},
        {"name": "Read Only",        "code": "READ_ONLY",     "desc": "View-only access",                     "weight": 0.5},
        {"name": "Department Head",  "code": "DEPT_HEAD",     "desc": "Department head access",               "weight": 1.6},
        {"name": "Auditor",          "code": "AUDITOR",       "desc": "Audit log access",                     "weight": 1.0},
        {"name": "IT Admin",         "code": "IT_ADMIN",      "desc": "IT systems access",                    "weight": 1.5},
        {"name": "Security Officer", "code": "SEC_OFFICER",   "desc": "Security & compliance access",         "weight": 1.4},
        {"name": "Data Analyst",     "code": "DATA_ANALYST",  "desc": "Data and reporting access",            "weight": 1.1},
        {"name": "Intern",           "code": "INTERN",        "desc": "Limited intern access",                "weight": 0.3},
        {"name": "Contractor",       "code": "CONTRACTOR",    "desc": "External contractor access",           "weight": 0.8},
        {"name": "Product Owner",    "code": "PRODUCT_OWNER", "desc": "Product ownership access",             "weight": 1.3},
        {"name": "Team Lead",        "code": "TEAM_LEAD",     "desc": "Technical team lead access",           "weight": 1.3},
        {"name": "QA Engineer",      "code": "QA_ENG",        "desc": "Quality assurance access",             "weight": 1.0},
        {"name": "DevOps Engineer",  "code": "DEVOPS_ENG",    "desc": "Infrastructure and deployment access", "weight": 1.2},
        {"name": "Customer Success", "code": "CS_REP",        "desc": "Customer success representative",      "weight": 1.0},
        {"name": "Sales Rep",        "code": "SALES_REP",     "desc": "Sales team access",                    "weight": 1.0},
        {"name": "Legal Counsel",    "code": "LEGAL",         "desc": "Legal and compliance access",          "weight": 1.2},
        {"name": "Executive",        "code": "EXECUTIVE",     "desc": "Executive level access",               "weight": 2.0},
        {"name": "Scrum Master",     "code": "SCRUM_MASTER",  "desc": "Agile process management",             "weight": 1.2},
        {"name": "Tech Lead",        "code": "TECH_LEAD",     "desc": "Technical leadership",                 "weight": 1.4},
        {"name": "Business Analyst", "code": "BIZ_ANALYST",   "desc": "Business analysis access",             "weight": 1.1},
        {"name": "Support Agent",    "code": "SUPPORT",       "desc": "Customer support access",              "weight": 0.9},
        {"name": "Marketing",        "code": "MARKETING",     "desc": "Marketing team access",                "weight": 1.0},
        {"name": "Trainer",          "code": "TRAINER",       "desc": "Training and development access",      "weight": 1.1},
    ]

    for r in role_data:
        if not await db.roles.find_first(where={"role_code": r["code"]}):
            await db.roles.create(data={
                "role_name":       r["name"],
                "role_code":       r["code"],
                "description":     r["desc"],
                "reviewer_weight": r["weight"],
                "updated_at":      NOW,
            })

    roles    = await db.roles.find_many()
    role_map = {r.role_code: r.role_id for r in roles}

    # =========================================================================
    # 6. TRANSACTION TYPES
    # =========================================================================
    print("  -> transaction_types")

    txn_types = [
        {"name": "Points Earned",        "code": "POINTS_EARNED",   "is_credit": True,  "desc": "Points credited from review"},
        {"name": "Points Redeemed",      "code": "POINTS_REDEEMED", "is_credit": False, "desc": "Points used for reward redemption"},
        {"name": "Points Adjustment",    "code": "POINTS_ADJ",      "is_credit": True,  "desc": "Manual adjustment by admin"},
        {"name": "Points Deduction",     "code": "POINTS_DED",      "is_credit": False, "desc": "Manual deduction by admin"},
        {"name": "Bonus Points",         "code": "BONUS",           "is_credit": True,  "desc": "Bonus points awarded"},
        {"name": "Points Expired",       "code": "POINTS_EXP",      "is_credit": False, "desc": "Points expired"},
        {"name": "Points Transfer In",   "code": "TRANSFER_IN",     "is_credit": True,  "desc": "Points transferred in"},
        {"name": "Points Transfer Out",  "code": "TRANSFER_OUT",    "is_credit": False, "desc": "Points transferred out"},
        {"name": "Welcome Bonus",        "code": "WELCOME_BONUS",   "is_credit": True,  "desc": "One-time welcome bonus"},
        {"name": "Anniversary Bonus",    "code": "ANNIV_BONUS",     "is_credit": True,  "desc": "Work anniversary bonus"},
        {"name": "Referral Bonus",       "code": "REFERRAL_BONUS",  "is_credit": True,  "desc": "Employee referral reward"},
        {"name": "Performance Bonus",    "code": "PERF_BONUS",      "is_credit": True,  "desc": "Performance based bonus"},
        {"name": "Correction Credit",    "code": "CORR_CREDIT",     "is_credit": True,  "desc": "Correction credit applied"},
        {"name": "Correction Debit",     "code": "CORR_DEBIT",      "is_credit": False, "desc": "Correction debit applied"},
        {"name": "Reversal",             "code": "REVERSAL",        "is_credit": True,  "desc": "Transaction reversal"},
        {"name": "Tax Deduction",        "code": "TAX_DED",         "is_credit": False, "desc": "Tax deducted from points"},
        {"name": "Spot Award",           "code": "SPOT_AWARD",      "is_credit": True,  "desc": "Spot recognition award"},
        {"name": "Team Award",           "code": "TEAM_AWARD",      "is_credit": True,  "desc": "Team achievement award"},
        {"name": "Learning Bonus",       "code": "LEARN_BONUS",     "is_credit": True,  "desc": "Learning completion bonus"},
        {"name": "Certification Bonus",  "code": "CERT_BONUS",      "is_credit": True,  "desc": "Professional cert bonus"},
        {"name": "Points Forfeiture",    "code": "FORFEIT",         "is_credit": False, "desc": "Points forfeited on exit"},
        {"name": "Upgrade Credit",       "code": "UPGRADE_CREDIT",  "is_credit": True,  "desc": "Tier upgrade credit"},
        {"name": "Promo Bonus",          "code": "PROMO_BONUS",     "is_credit": True,  "desc": "Promotional bonus"},
        {"name": "Charity Donation",     "code": "CHARITY",         "is_credit": False, "desc": "Points donated to charity"},
        {"name": "Gift Card Redemption", "code": "GIFT_REDEEM",     "is_credit": False, "desc": "Redeemed for gift card"},
        {"name": "Voucher Redemption",   "code": "VOUCHER_REDEEM",  "is_credit": False, "desc": "Redeemed for voucher"},
        {"name": "Cashback",             "code": "CASHBACK",        "is_credit": True,  "desc": "Cashback on redemption"},
        {"name": "Festival Bonus",       "code": "FESTIVAL_BONUS",  "is_credit": True,  "desc": "Festival season bonus"},
        {"name": "Manager Award",        "code": "MANAGER_AWARD",   "is_credit": True,  "desc": "Awarded by manager"},
        {"name": "Peer Recognition",     "code": "PEER_RECOG",      "is_credit": True,  "desc": "Peer-to-peer recognition"},
    ]

    for t in txn_types:
        if not await db.transaction_types.find_first(where={"type_code": t["code"]}):
            await db.transaction_types.create(data={
                "type_name":   t["name"],
                "type_code":   t["code"],
                "is_credit":   t["is_credit"],
                "description": t["desc"],
                "updated_at":  NOW,
            })

    txn_type_records = await db.transaction_types.find_many()
    txn_type_map     = {t.type_code: t.type_id for t in txn_type_records}

    # =========================================================================
    # 7. REWARD CATEGORIES
    # =========================================================================
    print("  -> reward_categories")

    reward_cat_data = [
        {"name": "Gift Cards",           "code": "GIFT_CARD",   "desc": "Digital and physical gift cards"},
        {"name": "Electronics",          "code": "ELECTRONICS", "desc": "Gadgets and electronics"},
        {"name": "Travel & Experiences", "code": "TRAVEL",      "desc": "Travel vouchers and experiences"},
        {"name": "Wellness",             "code": "WELLNESS",    "desc": "Health and wellness rewards"},
        {"name": "Learning",             "code": "LEARNING",    "desc": "Courses and certifications"},
        {"name": "Food & Dining",        "code": "FOOD",        "desc": "Restaurant and food vouchers"},
        {"name": "Fashion",              "code": "FASHION",     "desc": "Clothing and accessories"},
        {"name": "Home & Living",        "code": "HOME",        "desc": "Home appliances and decor"},
        {"name": "Entertainment",        "code": "ENTERTAIN",   "desc": "Movies, games, streaming"},
        {"name": "Charity",              "code": "CHARITY",     "desc": "Donate to charity"},
        {"name": "Sport & Fitness",      "code": "SPORT",       "desc": "Fitness equipment and memberships"},
        {"name": "Books & Media",        "code": "BOOKS",       "desc": "Books, magazines, audiobooks"},
        {"name": "Subscriptions",        "code": "SUBSCR",      "desc": "Software and service subscriptions"},
        {"name": "Transportation",       "code": "TRANSPORT",   "desc": "Cab, fuel, and transit"},
        {"name": "Company Merchandise",  "code": "MERCH",       "desc": "Company branded items"},
        {"name": "Professional Tools",   "code": "TOOLS",       "desc": "Work tools and software"},
        {"name": "Gaming",               "code": "GAMING",      "desc": "Games and gaming accessories"},
        {"name": "Art & Craft",          "code": "ART",         "desc": "Creative supplies"},
        {"name": "Childcare",            "code": "CHILDCARE",   "desc": "Childcare and family support"},
        {"name": "Pet Care",             "code": "PETCARE",     "desc": "Pet supplies and vet vouchers"},
        {"name": "Beauty & Personal",    "code": "BEAUTY",      "desc": "Beauty and grooming products"},
        {"name": "Photography",          "code": "PHOTO",       "desc": "Photography equipment"},
        {"name": "Musical",              "code": "MUSIC",       "desc": "Musical instruments and lessons"},
        {"name": "Outdoor",              "code": "OUTDOOR",     "desc": "Outdoor and adventure gear"},
        {"name": "Eco & Sustainable",    "code": "ECO",         "desc": "Eco-friendly products"},
        {"name": "Social Impact",        "code": "SOCIAL",      "desc": "Community and volunteering"},
        {"name": "Healthcare",           "code": "HEALTH",      "desc": "Medical and dental vouchers"},
        {"name": "Financial",            "code": "FINANCIAL",   "desc": "Investment and savings tools"},
        {"name": "Kids & Family",        "code": "KIDS",        "desc": "Family and kids activities"},
        {"name": "Luxury",               "code": "LUXURY",      "desc": "Premium luxury rewards"},
    ]

    for rc in reward_cat_data:
        if not await db.reward_categories.find_first(where={"category_code": rc["code"]}):
            await db.reward_categories.create(data={
                "category_name": rc["name"],
                "category_code": rc["code"],
                "description":   rc["desc"],
                "is_active":     True,
                "updated_at":    NOW,
            })

    reward_cats    = await db.reward_categories.find_many()
    reward_cat_map = {r.category_code: r.category_id for r in reward_cats}

    # =========================================================================
    # 8. REWARD CATALOG
    # =========================================================================
    print("  -> reward_catalog")

    catalog_data = [
        {"name": "Amazon Gift Card Rs500",     "code": "AMZ_500",     "cat": "GIFT_CARD",   "def_pts": 500,   "min": 400,  "max": 600,   "stock": 100},
        {"name": "Amazon Gift Card Rs1000",    "code": "AMZ_1000",    "cat": "GIFT_CARD",   "def_pts": 1000,  "min": 900,  "max": 1100,  "stock": 50},
        {"name": "Flipkart Voucher Rs500",     "code": "FLK_500",     "cat": "GIFT_CARD",   "def_pts": 500,   "min": 400,  "max": 600,   "stock": 80},
        {"name": "Apple AirPods",              "code": "AIRPODS",     "cat": "ELECTRONICS", "def_pts": 8000,  "min": 7500, "max": 9000,  "stock": 10},
        {"name": "Kindle eReader",             "code": "KINDLE",      "cat": "ELECTRONICS", "def_pts": 5000,  "min": 4500, "max": 5500,  "stock": 15},
        {"name": "Noise Smartwatch",           "code": "SMARTWATCH",  "cat": "ELECTRONICS", "def_pts": 3000,  "min": 2500, "max": 3500,  "stock": 20},
        {"name": "Weekend Getaway Voucher",    "code": "WEEKEND",     "cat": "TRAVEL",      "def_pts": 10000, "min": 9000, "max": 11000, "stock": 5},
        {"name": "Flight Voucher Rs3000",      "code": "FLIGHT_3K",   "cat": "TRAVEL",      "def_pts": 3000,  "min": 2500, "max": 3500,  "stock": 30},
        {"name": "Gym Membership 3 Months",    "code": "GYM_3M",      "cat": "WELLNESS",    "def_pts": 2500,  "min": 2000, "max": 3000,  "stock": 25},
        {"name": "Yoga Class Pack",            "code": "YOGA",        "cat": "WELLNESS",    "def_pts": 1500,  "min": 1200, "max": 1800,  "stock": 40},
        {"name": "Udemy Course Bundle",        "code": "UDEMY",       "cat": "LEARNING",    "def_pts": 2000,  "min": 1800, "max": 2200,  "stock": 60},
        {"name": "Coursera Plus 1 Month",      "code": "COURSERA",    "cat": "LEARNING",    "def_pts": 1500,  "min": 1200, "max": 1800,  "stock": 50},
        {"name": "Swiggy Voucher Rs500",       "code": "SWIGGY_500",  "cat": "FOOD",        "def_pts": 500,   "min": 400,  "max": 600,   "stock": 150},
        {"name": "Zomato Gold 1 Month",        "code": "ZOMATO_GOLD", "cat": "FOOD",        "def_pts": 800,   "min": 700,  "max": 900,   "stock": 60},
        {"name": "Myntra Voucher Rs1000",      "code": "MYNTRA_1K",   "cat": "FASHION",     "def_pts": 1000,  "min": 900,  "max": 1100,  "stock": 40},
        {"name": "IKEA Gift Card Rs2000",      "code": "IKEA_2K",     "cat": "HOME",        "def_pts": 2000,  "min": 1800, "max": 2200,  "stock": 20},
        {"name": "Netflix 3 Months",           "code": "NETFLIX_3M",  "cat": "ENTERTAIN",   "def_pts": 1200,  "min": 1000, "max": 1400,  "stock": 80},
        {"name": "Spotify Premium 6 Months",   "code": "SPOTIFY_6M",  "cat": "ENTERTAIN",   "def_pts": 600,   "min": 500,  "max": 700,   "stock": 100},
        {"name": "Sports Jersey",              "code": "JERSEY",      "cat": "SPORT",       "def_pts": 1500,  "min": 1200, "max": 1800,  "stock": 30},
        {"name": "OReilly Subscription",       "code": "OREILLY",     "cat": "BOOKS",       "def_pts": 3000,  "min": 2500, "max": 3500,  "stock": 25},
        {"name": "GitHub Copilot 1 Year",      "code": "GH_COPILOT",  "cat": "TOOLS",       "def_pts": 2500,  "min": 2200, "max": 2800,  "stock": 40},
        {"name": "Company T-Shirt",            "code": "TSHIRT",      "cat": "MERCH",       "def_pts": 300,   "min": 200,  "max": 400,   "stock": 200},
        {"name": "Company Hoodie",             "code": "HOODIE",      "cat": "MERCH",       "def_pts": 600,   "min": 500,  "max": 700,   "stock": 100},
        {"name": "PlayStation Store Rs2000",   "code": "PSN_2K",      "cat": "GAMING",      "def_pts": 2000,  "min": 1800, "max": 2200,  "stock": 20},
        {"name": "Donate 500 pts to Charity",  "code": "CHARITY_500", "cat": "CHARITY",     "def_pts": 500,   "min": 500,  "max": 500,   "stock": 999},
        {"name": "Ola Cab Credits Rs500",      "code": "OLA_500",     "cat": "TRANSPORT",   "def_pts": 500,   "min": 400,  "max": 600,   "stock": 120},
        {"name": "Cultfit Pack 1 Month",       "code": "CULT_1M",     "cat": "WELLNESS",    "def_pts": 2000,  "min": 1800, "max": 2200,  "stock": 30},
        {"name": "LinkedIn Learning 1 Month",  "code": "LI_LEARN",    "cat": "LEARNING",    "def_pts": 1000,  "min": 800,  "max": 1200,  "stock": 70},
        {"name": "Apple App Store Rs1000",     "code": "APPSTORE_1K", "cat": "GIFT_CARD",   "def_pts": 1000,  "min": 900,  "max": 1100,  "stock": 60},
        {"name": "Luxury Spa Voucher",         "code": "SPA",         "cat": "LUXURY",      "def_pts": 5000,  "min": 4500, "max": 5500,  "stock": 8},
    ]

    for c in catalog_data:
        if not await db.reward_catalog.find_first(where={"reward_code": c["code"]}):
            await db.reward_catalog.create(data={
                "reward_name":     c["name"],
                "reward_code":     c["code"],
                "category_id":     reward_cat_map[c["cat"]],
                "default_points":  c["def_pts"],
                "min_points":      c["min"],
                "max_points":      c["max"],
                "available_stock": c["stock"],
                "is_active":       True,
                "updated_at":      NOW,
            })

    catalog_items = await db.reward_catalog.find_many()
    catalog_map   = {c.reward_code: c.catalog_id for c in catalog_items}

    # =========================================================================
    # 9. REVIEW CATEGORIES
    # =========================================================================
    print("  -> review_categories")

    review_cat_data = [
        {"code": "INNOVATION",    "name": "Innovation",            "multiplier": 1.5, "desc": "Creative and innovative contributions"},
        {"code": "TEAMWORK",      "name": "Teamwork",              "multiplier": 1.2, "desc": "Collaboration and team support"},
        {"code": "LEADERSHIP",    "name": "Leadership",            "multiplier": 1.8, "desc": "Leadership and mentoring"},
        {"code": "DELIVERY",      "name": "Delivery Excellence",   "multiplier": 1.3, "desc": "On-time and quality delivery"},
        {"code": "CUSTOMER",      "name": "Customer Focus",        "multiplier": 1.4, "desc": "Customer satisfaction impact"},
        {"code": "LEARNING",      "name": "Learning & Growth",     "multiplier": 1.1, "desc": "Self-improvement and upskilling"},
        {"code": "COMMUNICATION", "name": "Communication",         "multiplier": 1.1, "desc": "Clear and effective communication"},
        {"code": "INITIATIVE",    "name": "Initiative",            "multiplier": 1.3, "desc": "Proactive problem solving"},
        {"code": "QUALITY",       "name": "Quality",               "multiplier": 1.4, "desc": "Quality of work output"},
        {"code": "MENTORSHIP",    "name": "Mentorship",            "multiplier": 1.6, "desc": "Mentoring junior team members"},
        {"code": "PROCESS",       "name": "Process Improvement",   "multiplier": 1.2, "desc": "Improving team processes"},
        {"code": "SAFETY",        "name": "Safety & Compliance",   "multiplier": 1.5, "desc": "Safety and compliance adherence"},
        {"code": "DIVERSITY",     "name": "Diversity & Inclusion", "multiplier": 1.3, "desc": "Promoting D&I in the workplace"},
        {"code": "SUSTAINABILITY","name": "Sustainability",        "multiplier": 1.2, "desc": "Environmentally responsible actions"},
        {"code": "WELLBEING",     "name": "Wellbeing Advocate",    "multiplier": 1.1, "desc": "Promoting team wellbeing"},
        {"code": "TECHNICAL",     "name": "Technical Excellence",  "multiplier": 1.5, "desc": "Deep technical contribution"},
        {"code": "COLLABORATION", "name": "Cross-team Collab",     "multiplier": 1.3, "desc": "Working across departments"},
        {"code": "OWNERSHIP",     "name": "Ownership",             "multiplier": 1.4, "desc": "Taking full ownership of tasks"},
        {"code": "RESILIENCE",    "name": "Resilience",            "multiplier": 1.2, "desc": "Handling pressure and setbacks"},
        {"code": "CREATIVITY",    "name": "Creativity",            "multiplier": 1.3, "desc": "Creative approaches and ideas"},
        {"code": "AGILITY",       "name": "Agility",               "multiplier": 1.2, "desc": "Adapting quickly to change"},
        {"code": "INTEGRITY",     "name": "Integrity",             "multiplier": 1.5, "desc": "Ethical behaviour and honesty"},
        {"code": "EMPATHY",       "name": "Empathy",               "multiplier": 1.1, "desc": "Understanding and empathy"},
        {"code": "DECISIVENESS",  "name": "Decisiveness",          "multiplier": 1.3, "desc": "Making clear and timely decisions"},
        {"code": "IMPACT",        "name": "Business Impact",       "multiplier": 1.6, "desc": "Measurable business impact"},
        {"code": "COACHING",      "name": "Coaching",              "multiplier": 1.4, "desc": "Coaching and developing others"},
        {"code": "STRATEGIC",     "name": "Strategic Thinking",    "multiplier": 1.7, "desc": "Long-term strategic planning"},
        {"code": "EXECUTION",     "name": "Execution Speed",       "multiplier": 1.2, "desc": "Fast and efficient execution"},
        {"code": "TRUST",         "name": "Trust Building",        "multiplier": 1.3, "desc": "Building trust across teams"},
        {"code": "ACCOUNTABILITY","name": "Accountability",        "multiplier": 1.4, "desc": "Holding self and others accountable"},
    ]

    for rc in review_cat_data:
        if not await db.review_categories.find_first(where={"category_code": rc["code"]}):
            await db.review_categories.create(data={
                "category_code": rc["code"],
                "category_name": rc["name"],
                "multiplier":    rc["multiplier"],
                "description":   rc["desc"],
                "is_active":     True,
                "updated_at":    NOW,
            })

    review_cats    = await db.review_categories.find_many()
    review_cat_map = {r.category_code: r.category_id for r in review_cats}

    # =========================================================================
    # 10. EMPLOYEES
    # =========================================================================
    print("  -> employees")

    admin_emp = await db.employees.find_first(where={"username": "admin.user"})
    if not admin_emp:
        admin_emp = await db.employees.create(data={
            "username":        "admin.user",
            "email":           "admin@company.com",
            "password_hash":   HASH,
            "designation_id":  desig_map["CEO"],
            "department_id":   dept_map["EL"],
            "status_id":       emp_active_status.status_id,
            "date_of_joining": datetime(2020, 1, 1),
            "date_of_birth":   datetime(1985, 3, 15),
            "updated_at":      NOW,
        })

    fixed_employees = [
        {"username": "jane.smith",          "email": "jane.smith@company.com",          "desig": "VP",    "dept": "HR",     "doj": "2020-03-10", "dob": "1988-07-22"},
        {"username": "shubrajit.deb",       "email": "shubrajitdeb180603@gmail.com",    "desig": "SENG",  "dept": "BE",     "doj": "2022-06-18", "dob": "2003-06-18"},
        {"username": "prasun.chakraborty",  "email": "nothingshere21@gmail.com",        "desig": "ENG",   "dept": "BE",     "doj": "2023-01-15", "dob": "2002-09-21"},
        {"username": "midanka.lahon",       "email": "midankalahon@gmail.com",          "desig": "ENG",   "dept": "FE",     "doj": "2023-02-20", "dob": "2001-11-05"},
        {"username": "swarup.das",          "email": "swarup1to3@gmail.com",            "desig": "SENG",  "dept": "BE",     "doj": "2021-08-01", "dob": "1998-03-30"},
        {"username": "mrinmoy.kashyap",     "email": "mrinmoykashyap.mk@gmail.com",     "desig": "ENG",   "dept": "QA",     "doj": "2022-11-14", "dob": "2000-05-14"},
        {"username": "rishav.bora",         "email": "rishavbora550@gmail.com",         "desig": "ENG",   "dept": "FE",     "doj": "2023-04-03", "dob": "2001-08-12"},
        {"username": "aminul.islam",        "email": "animul7535@gmail.com",            "desig": "JENG",  "dept": "BE",     "doj": "2024-01-08", "dob": "2002-12-25"},
        {"username": "bikash.bora",         "email": "borab796@gmail.com",              "desig": "JENG",  "dept": "FE",     "doj": "2024-02-15", "dob": "2003-01-19"},
        {"username": "dipam.barman",        "email": "dipambarman3@gmail.com",          "desig": "ENG",   "dept": "DA",     "doj": "2023-07-10", "dob": "2001-04-07"},
        {"username": "gautam.hazarika",     "email": "gautamhazarika01@gmail.com",      "desig": "SENG",  "dept": "DA",     "doj": "2021-05-20", "dob": "1997-01-01"},
        {"username": "arijit.banik",        "email": "arijitb017@gmail.com",            "desig": "ENG",   "dept": "MOB",    "doj": "2022-09-05", "dob": "1999-07-17"},
        {"username": "binit.goswami",       "email": "binitkgsmile2005@gmail.com",      "desig": "JENG",  "dept": "MOB",    "doj": "2024-03-01", "dob": "2005-06-20"},
    ]

    dummy_employees = [
        {"username": "alice.wong",     "email": "alice.wong@company.com",     "desig": "SDIR",  "dept": "FIN",    "doj": "2019-06-01", "dob": "1986-04-10"},
        {"username": "bob.sharma",     "email": "bob.sharma@company.com",     "desig": "MGR",   "dept": "PM",     "doj": "2020-08-15", "dob": "1990-09-25"},
        {"username": "carol.nair",     "email": "carol.nair@company.com",     "desig": "SENG",  "dept": "DEVOPS", "doj": "2021-01-20", "dob": "1993-02-14"},
        {"username": "david.paul",     "email": "david.paul@company.com",     "desig": "SMGR",  "dept": "CS",     "doj": "2019-11-11", "dob": "1987-11-11"},
        {"username": "emma.rodrigues", "email": "emma.rodrigues@company.com", "desig": "ENG",   "dept": "SEC",    "doj": "2022-04-04", "dob": "1996-06-30"},
        {"username": "frank.das",      "email": "frank.das@company.com",      "desig": "TL",    "dept": "AI",     "doj": "2021-07-07", "dob": "1994-03-22"},
        {"username": "grace.hopper",   "email": "grace.hopper@company.com",   "desig": "DIR",   "dept": "PLE",    "doj": "2018-03-19", "dob": "1984-12-09"},
        {"username": "henry.ford",     "email": "henry.ford@company.com",     "desig": "STENG", "dept": "BE",     "doj": "2020-05-05", "dob": "1991-07-04"},
        {"username": "iris.patel",     "email": "iris.patel@company.com",     "desig": "ANA",   "dept": "BI",     "doj": "2023-09-01", "dob": "1998-08-18"},
        {"username": "james.bond",     "email": "james.bond@company.com",     "desig": "SCON",  "dept": "LEG",    "doj": "2020-10-10", "dob": "1989-10-07"},
        {"username": "kate.miller",    "email": "kate.miller@company.com",    "desig": "PMGR",  "dept": "PM",     "doj": "2021-12-01", "dob": "1992-05-16"},
        {"username": "leo.king",       "email": "leo.king@company.com",       "desig": "HOD",   "dept": "MKT",    "doj": "2019-02-28", "dob": "1985-08-28"},
        {"username": "maya.verma",     "email": "maya.verma@company.com",     "desig": "SANA",  "dept": "FIN",    "doj": "2022-03-15", "dob": "1995-10-30"},
        {"username": "neil.gupta",     "email": "neil.gupta@company.com",     "desig": "LENG",  "dept": "BE",     "doj": "2021-06-21", "dob": "1993-06-21"},
        {"username": "olivia.khan",    "email": "olivia.khan@company.com",    "desig": "ENG",   "dept": "QA",     "doj": "2023-11-11", "dob": "2000-11-11"},
        {"username": "peter.sen",      "email": "peter.sen@company.com",      "desig": "JENG",  "dept": "FE",     "doj": "2024-04-01", "dob": "2002-04-01"},
    ]

    all_employees = fixed_employees + dummy_employees
    emp_map = {"admin.user": admin_emp.employee_id}

    for e in all_employees:
        existing_emp = await db.employees.find_first(where={"username": e["username"]})
        if existing_emp:
            emp_map[e["username"]] = existing_emp.employee_id
        else:
            new_emp = await db.employees.create(data={
                "username":        e["username"],
                "email":           e["email"],
                "password_hash":   HASH,
                "designation_id":  desig_map[e["desig"]],
                "department_id":   dept_map[e["dept"]],
                "manager_id":      admin_emp.employee_id,
                "status_id":       emp_active_status.status_id,
                "date_of_joining": datetime.fromisoformat(e["doj"]),
                "date_of_birth":   datetime.fromisoformat(e["dob"]),
                "created_by":      admin_emp.employee_id,
                "updated_at":      NOW,
                "updated_by":      admin_emp.employee_id,
            })
            emp_map[e["username"]] = new_emp.employee_id

    # =========================================================================
    # 11. EMPLOYEE ROLES
    # =========================================================================
    print("  -> employee_roles")

    emp_role_assignments = [
        {"username": "admin.user",         "role_code": "SUPER_ADMIN"},
        {"username": "admin.user",         "role_code": "ADMIN"},
        {"username": "jane.smith",         "role_code": "HR_MANAGER"},
        {"username": "jane.smith",         "role_code": "MANAGER"},
        {"username": "shubrajit.deb",      "role_code": "SENIOR_EMP"},
        {"username": "prasun.chakraborty", "role_code": "EMPLOYEE"},
        {"username": "midanka.lahon",      "role_code": "EMPLOYEE"},
        {"username": "swarup.das",         "role_code": "SENIOR_EMP"},
        {"username": "mrinmoy.kashyap",    "role_code": "QA_ENG"},
        {"username": "rishav.bora",        "role_code": "EMPLOYEE"},
        {"username": "aminul.islam",       "role_code": "EMPLOYEE"},
        {"username": "bikash.bora",        "role_code": "EMPLOYEE"},
        {"username": "dipam.barman",       "role_code": "DATA_ANALYST"},
        {"username": "gautam.hazarika",    "role_code": "SENIOR_EMP"},
        {"username": "arijit.banik",       "role_code": "EMPLOYEE"},
        {"username": "binit.goswami",      "role_code": "INTERN"},
        {"username": "alice.wong",         "role_code": "FINANCE"},
        {"username": "bob.sharma",         "role_code": "PRODUCT_OWNER"},
        {"username": "carol.nair",         "role_code": "DEVOPS_ENG"},
        {"username": "david.paul",         "role_code": "CS_REP"},
        {"username": "emma.rodrigues",     "role_code": "EMPLOYEE"},
        {"username": "frank.das",          "role_code": "TECH_LEAD"},
        {"username": "grace.hopper",       "role_code": "DEPT_HEAD"},
        {"username": "henry.ford",         "role_code": "SENIOR_EMP"},
        {"username": "iris.patel",         "role_code": "DATA_ANALYST"},
        {"username": "james.bond",         "role_code": "LEGAL"},
        {"username": "kate.miller",        "role_code": "PRODUCT_OWNER"},
        {"username": "leo.king",           "role_code": "MARKETING"},
        {"username": "maya.verma",         "role_code": "FINANCE"},
        {"username": "neil.gupta",         "role_code": "TEAM_LEAD"},
    ]

    for ra in emp_role_assignments:
        emp_id  = emp_map.get(ra["username"])
        role_id = role_map.get(ra["role_code"])
        if not emp_id or not role_id:
            continue
        if not await db.employee_roles.find_first(where={"employee_id": emp_id, "role_id": role_id, "is_active": True}):
            await db.employee_roles.create(data={
                "employee_id": emp_id,
                "role_id":     role_id,
                "assigned_by": admin_emp.employee_id,
                "created_by":  admin_emp.employee_id,
                "updated_at":  NOW,
                "updated_by":  admin_emp.employee_id,
            })

    # =========================================================================
    # 12. WALLETS
    # =========================================================================
    print("  -> wallets")

    wallet_points = {
        "admin.user":         {"avail": 999999, "redeemed": 0,    "total": 999999},
        "jane.smith":         {"avail": 8500,   "redeemed": 500,  "total": 9000},
        "shubrajit.deb":      {"avail": 3200,   "redeemed": 300,  "total": 3500},
        "prasun.chakraborty": {"avail": 2800,   "redeemed": 200,  "total": 3000},
        "midanka.lahon":      {"avail": 2500,   "redeemed": 0,    "total": 2500},
        "swarup.das":         {"avail": 4500,   "redeemed": 500,  "total": 5000},
        "mrinmoy.kashyap":    {"avail": 2100,   "redeemed": 400,  "total": 2500},
        "rishav.bora":        {"avail": 1800,   "redeemed": 200,  "total": 2000},
        "aminul.islam":       {"avail": 900,    "redeemed": 0,    "total": 900},
        "bikash.bora":        {"avail": 750,    "redeemed": 0,    "total": 750},
        "dipam.barman":       {"avail": 2200,   "redeemed": 300,  "total": 2500},
        "gautam.hazarika":    {"avail": 7300,   "redeemed": 700,  "total": 8000},
        "arijit.banik":       {"avail": 1600,   "redeemed": 0,    "total": 1600},
        "binit.goswami":      {"avail": 400,    "redeemed": 0,    "total": 400},
        "alice.wong":         {"avail": 13000,  "redeemed": 1000, "total": 14000},
        "bob.sharma":         {"avail": 5500,   "redeemed": 500,  "total": 6000},
        "carol.nair":         {"avail": 3800,   "redeemed": 200,  "total": 4000},
        "david.paul":         {"avail": 4200,   "redeemed": 800,  "total": 5000},
        "emma.rodrigues":     {"avail": 1500,   "redeemed": 0,    "total": 1500},
        "frank.das":          {"avail": 6200,   "redeemed": 800,  "total": 7000},
        "grace.hopper":       {"avail": 5800,   "redeemed": 1500, "total": 7300},
        "henry.ford":         {"avail": 3500,   "redeemed": 0,    "total": 3500},
        "iris.patel":         {"avail": 1200,   "redeemed": 0,    "total": 1200},
        "james.bond":         {"avail": 6400,   "redeemed": 600,  "total": 7000},
        "kate.miller":        {"avail": 4800,   "redeemed": 200,  "total": 5000},
        "leo.king":           {"avail": 3100,   "redeemed": 400,  "total": 3500},
        "maya.verma":         {"avail": 2700,   "redeemed": 300,  "total": 3000},
        "neil.gupta":         {"avail": 5100,   "redeemed": 900,  "total": 6000},
        "olivia.khan":        {"avail": 800,    "redeemed": 0,    "total": 800},
        "peter.sen":          {"avail": 350,    "redeemed": 0,    "total": 350},
    }

    wallet_map = {}
    for username, pts in wallet_points.items():
        emp_id = emp_map.get(username)
        if not emp_id:
            continue
        existing_wallet = await db.wallets.find_first(where={"employee_id": emp_id})
        if existing_wallet:
            wallet_map[username] = existing_wallet.wallet_id
        else:
            new_wallet = await db.wallets.create(data={
                "employee_id":         emp_id,
                "available_points":    pts["avail"],
                "redeemed_points":     pts["redeemed"],
                "total_earned_points": pts["total"],
                "created_by":          admin_emp.employee_id,
                "updated_at":          NOW,
                "updated_by":          admin_emp.employee_id,
            })
            wallet_map[username] = new_wallet.wallet_id

    # =========================================================================
    # 13. TRANSACTIONS
    # =========================================================================
    print("  -> transactions")

    txn_earned  = txn_type_map["POINTS_EARNED"]
    txn_counter = 1

    for username, wallet_id in wallet_map.items():
        pts = wallet_points.get(username, {}).get("total", 0)
        if pts == 0:
            continue
        ref = f"TXN-SEED-{str(txn_counter).zfill(5)}"
        txn_counter += 1
        if not await db.transactions.find_first(where={"reference_number": ref}):
            await db.transactions.create(data={
                "wallet_id":           wallet_id,
                "amount":              pts,
                "transaction_type_id": txn_earned,
                "status_id":           txn_completed.status_id,
                "reference_number":    ref,
                "description":         f"Seed initial points for {username}",
                "created_by":          admin_emp.employee_id,
                "updated_at":          NOW,
                "updated_by":          admin_emp.employee_id,
            })

    # =========================================================================
    # 14. REVIEWS
    # =========================================================================
    print("  -> reviews")

    review_pairs = [
        {"reviewer": "admin.user",         "receiver": "shubrajit.deb",      "comment": "Outstanding backend work on the payments module.", "pts": 1200, "cats": ["TECHNICAL", "DELIVERY"]},
        {"reviewer": "jane.smith",         "receiver": "prasun.chakraborty",  "comment": "Great initiative on the API redesign project.",     "pts": 900,  "cats": ["INITIATIVE", "INNOVATION"]},
        {"reviewer": "alice.wong",         "receiver": "swarup.das",          "comment": "Consistently delivers high quality code.",          "pts": 1000, "cats": ["QUALITY", "DELIVERY"]},
        {"reviewer": "grace.hopper",       "receiver": "gautam.hazarika",     "comment": "Excellent data pipeline work this quarter.",        "pts": 1500, "cats": ["TECHNICAL", "IMPACT"]},
        {"reviewer": "frank.das",          "receiver": "arijit.banik",        "comment": "Strong mobile dev skills and great attitude.",      "pts": 700,  "cats": ["TECHNICAL", "TEAMWORK"]},
        {"reviewer": "admin.user",         "receiver": "jane.smith",          "comment": "Exceptional HR leadership and team building.",      "pts": 2000, "cats": ["LEADERSHIP", "MENTORSHIP"]},
        {"reviewer": "neil.gupta",         "receiver": "midanka.lahon",       "comment": "Clean frontend code and pixel-perfect UI work.",    "pts": 600,  "cats": ["QUALITY", "CREATIVITY"]},
        {"reviewer": "bob.sharma",         "receiver": "dipam.barman",        "comment": "Insightful analytics dashboards helped the team.",  "pts": 800,  "cats": ["IMPACT", "COMMUNICATION"]},
        {"reviewer": "james.bond",         "receiver": "alice.wong",          "comment": "Exceptional financial planning and compliance.",    "pts": 1800, "cats": ["STRATEGIC", "INTEGRITY"]},
        {"reviewer": "kate.miller",        "receiver": "frank.das",           "comment": "Strong technical leadership on platform work.",     "pts": 1400, "cats": ["LEADERSHIP", "TECHNICAL"]},
        {"reviewer": "swarup.das",         "receiver": "shubrajit.deb",       "comment": "Helped unblock the team multiple times.",           "pts": 500,  "cats": ["TEAMWORK", "INITIATIVE"]},
        {"reviewer": "gautam.hazarika",    "receiver": "prasun.chakraborty",  "comment": "Solid contributions to the data APIs.",             "pts": 600,  "cats": ["DELIVERY", "QUALITY"]},
        {"reviewer": "admin.user",         "receiver": "alice.wong",          "comment": "Top financial management this year.",               "pts": 2500, "cats": ["IMPACT", "STRATEGIC"]},
        {"reviewer": "carol.nair",         "receiver": "henry.ford",          "comment": "Great backend architecture contribution.",          "pts": 900,  "cats": ["TECHNICAL", "OWNERSHIP"]},
        {"reviewer": "david.paul",         "receiver": "kate.miller",         "comment": "Clear product vision and execution.",               "pts": 1000, "cats": ["STRATEGIC", "DELIVERY"]},
        {"reviewer": "leo.king",           "receiver": "bob.sharma",          "comment": "Excellent product roadmap planning.",               "pts": 1100, "cats": ["STRATEGIC", "LEADERSHIP"]},
        {"reviewer": "iris.patel",         "receiver": "dipam.barman",        "comment": "Reliable BI reports that saved hours weekly.",      "pts": 700,  "cats": ["IMPACT", "QUALITY"]},
        {"reviewer": "henry.ford",         "receiver": "neil.gupta",          "comment": "Excellent mentorship to junior devs.",              "pts": 900,  "cats": ["MENTORSHIP", "TEAMWORK"]},
        {"reviewer": "olivia.khan",        "receiver": "mrinmoy.kashyap",     "comment": "Thorough QA process improved release quality.",     "pts": 600,  "cats": ["QUALITY", "PROCESS"]},
        {"reviewer": "maya.verma",         "receiver": "james.bond",          "comment": "Solid legal guidance on compliance matters.",       "pts": 1200, "cats": ["INTEGRITY", "STRATEGIC"]},
        {"reviewer": "admin.user",         "receiver": "grace.hopper",        "comment": "Exceptional technical and team leadership.",        "pts": 2200, "cats": ["LEADERSHIP", "TECHNICAL"]},
        {"reviewer": "shubrajit.deb",      "receiver": "rishav.bora",         "comment": "Good progress on frontend components.",             "pts": 400,  "cats": ["DELIVERY", "LEARNING"]},
        {"reviewer": "prasun.chakraborty", "receiver": "aminul.islam",        "comment": "Fast learner, good first contributions.",           "pts": 350,  "cats": ["LEARNING", "INITIATIVE"]},
        {"reviewer": "frank.das",          "receiver": "carol.nair",          "comment": "Infra automation saved significant time.",          "pts": 1300, "cats": ["INNOVATION", "IMPACT"]},
        {"reviewer": "grace.hopper",       "receiver": "neil.gupta",          "comment": "Strong technical leadership on BE team.",           "pts": 1100, "cats": ["LEADERSHIP", "TECHNICAL"]},
        {"reviewer": "admin.user",         "receiver": "james.bond",          "comment": "Outstanding legal strategy and compliance work.",   "pts": 1500, "cats": ["STRATEGIC", "INTEGRITY"]},
        {"reviewer": "jane.smith",         "receiver": "binit.goswami",       "comment": "Good start as an intern, shows great potential.",   "pts": 200,  "cats": ["LEARNING", "INITIATIVE"]},
        {"reviewer": "alice.wong",         "receiver": "maya.verma",          "comment": "Accurate financial reporting and analysis.",        "pts": 800,  "cats": ["QUALITY", "DELIVERY"]},
        {"reviewer": "bob.sharma",         "receiver": "kate.miller",         "comment": "Great product thinking and stakeholder management.","pts": 950,  "cats": ["STRATEGIC", "COMMUNICATION"]},
        {"reviewer": "leo.king",           "receiver": "david.paul",          "comment": "Excellent customer success outcomes this quarter.", "pts": 1000, "cats": ["CUSTOMER", "IMPACT"]},
    ]

    for r in review_pairs:
        reviewer_id = emp_map.get(r["reviewer"])
        receiver_id = emp_map.get(r["receiver"])
        if not reviewer_id or not receiver_id:
            continue
        if await db.reviews.find_first(where={"reviewer_id": reviewer_id, "receiver_id": receiver_id}):
            continue

        review = await db.reviews.create(data={
            "reviewer_id": reviewer_id,
            "receiver_id": receiver_id,
            "comment":     r["comment"],
            "status_id":   rev_approved.status_id,
            "raw_points":  r["pts"],
            "created_by":  reviewer_id,
            "updated_at":  NOW,
            "updated_by":  reviewer_id,
        })

        for cat_code in r["cats"]:
            cat_id = review_cat_map.get(cat_code)
            cat    = next((rc for rc in review_cats if rc.category_code == cat_code), None)
            if not cat_id or not cat:
                continue
            if not await db.review_category_tags.find_first(where={"review_id": review.review_id, "category_id": cat_id}):
                await db.review_category_tags.create(data={
                    "review_id":              review.review_id,
                    "category_id":            cat_id,
                    "multiplier_snapshot":    cat.multiplier,
                    "category_code_snapshot": cat.category_code,
                })

    # =========================================================================
    # 15. REWARD HISTORY
    # =========================================================================
    print("  -> reward_history")

    reward_history_data = [
        {"username": "jane.smith",         "catalog_code": "NETFLIX_3M",  "pts": 1200,  "comment": "Monthly Netflix reward"},
        {"username": "alice.wong",         "catalog_code": "AMZ_1000",    "pts": 1000,  "comment": "Amazon gift card reward"},
        {"username": "gautam.hazarika",    "catalog_code": "GYM_3M",      "pts": 2500,  "comment": "Gym membership reward"},
        {"username": "swarup.das",         "catalog_code": "UDEMY",       "pts": 2000,  "comment": "Learning course reward"},
        {"username": "frank.das",          "catalog_code": "AIRPODS",     "pts": 8000,  "comment": "Electronics reward"},
        {"username": "grace.hopper",       "catalog_code": "WEEKEND",     "pts": 10000, "comment": "Weekend getaway"},
        {"username": "james.bond",         "catalog_code": "AMZ_500",     "pts": 500,   "comment": "Gift card"},
        {"username": "shubrajit.deb",      "catalog_code": "SWIGGY_500",  "pts": 500,   "comment": "Food voucher"},
        {"username": "neil.gupta",         "catalog_code": "COURSERA",    "pts": 1500,  "comment": "Coursera subscription"},
        {"username": "bob.sharma",         "catalog_code": "TSHIRT",      "pts": 300,   "comment": "Company merch"},
        {"username": "carol.nair",         "catalog_code": "SPOTIFY_6M",  "pts": 600,   "comment": "Music subscription"},
        {"username": "david.paul",         "catalog_code": "OLA_500",     "pts": 500,   "comment": "Cab credits"},
        {"username": "kate.miller",        "catalog_code": "FLK_500",     "pts": 500,   "comment": "Flipkart voucher"},
        {"username": "henry.ford",         "catalog_code": "GH_COPILOT",  "pts": 2500,  "comment": "GitHub Copilot"},
        {"username": "dipam.barman",       "catalog_code": "LI_LEARN",    "pts": 1000,  "comment": "LinkedIn Learning"},
        {"username": "maya.verma",         "catalog_code": "AMZ_500",     "pts": 500,   "comment": "Gift card"},
        {"username": "prasun.chakraborty", "catalog_code": "SWIGGY_500",  "pts": 500,   "comment": "Food voucher"},
        {"username": "leo.king",           "catalog_code": "HOODIE",      "pts": 600,   "comment": "Company hoodie"},
        {"username": "arijit.banik",       "catalog_code": "TSHIRT",      "pts": 300,   "comment": "Company merch"},
        {"username": "iris.patel",         "catalog_code": "YOGA",        "pts": 1500,  "comment": "Yoga class pack"},
        {"username": "james.bond",         "catalog_code": "OREILLY",     "pts": 3000,  "comment": "OReilly subscription"},
        {"username": "alice.wong",         "catalog_code": "FLIGHT_3K",   "pts": 3000,  "comment": "Flight voucher"},
        {"username": "grace.hopper",       "catalog_code": "SPA",         "pts": 5000,  "comment": "Luxury spa voucher"},
        {"username": "frank.das",          "catalog_code": "PSN_2K",      "pts": 2000,  "comment": "PlayStation credits"},
        {"username": "gautam.hazarika",    "catalog_code": "KINDLE",      "pts": 5000,  "comment": "Kindle eReader"},
        {"username": "neil.gupta",         "catalog_code": "CULT_1M",     "pts": 2000,  "comment": "Cultfit pack"},
        {"username": "shubrajit.deb",      "catalog_code": "ZOMATO_GOLD", "pts": 800,   "comment": "Zomato Gold"},
        {"username": "swarup.das",         "catalog_code": "APPSTORE_1K", "pts": 1000,  "comment": "App Store credit"},
        {"username": "mrinmoy.kashyap",    "catalog_code": "SWIGGY_500",  "pts": 500,   "comment": "Food voucher"},
        {"username": "midanka.lahon",      "catalog_code": "TSHIRT",      "pts": 300,   "comment": "Company merch"},
    ]

    for rh in reward_history_data:
        wallet_id  = wallet_map.get(rh["username"])
        catalog_id = catalog_map.get(rh["catalog_code"])
        if not wallet_id or not catalog_id:
            continue
        await db.reward_history.create(data={
            "wallet_id":  wallet_id,
            "catalog_id": catalog_id,
            "granted_by": admin_emp.employee_id,
            "points":     rh["pts"],
            "comment":    rh["comment"],
            "created_by": admin_emp.employee_id,
            "updated_at": NOW,
            "updated_by": admin_emp.employee_id,
        })

    # =========================================================================
    # 16. NOTIFICATIONS
    # =========================================================================
    print("  -> notifications")

    notif_data = [
        {"username": "shubrajit.deb",      "title": "You received a review!",      "message": "admin.user gave you a recognition. Check it out!", "type": "REVIEW"},
        {"username": "prasun.chakraborty", "title": "New review received",          "message": "jane.smith recognised your work. View now.",        "type": "REVIEW"},
        {"username": "jane.smith",         "title": "Points credited",              "message": "2000 points have been added to your wallet.",        "type": "POINTS"},
        {"username": "alice.wong",         "title": "Points credited",              "message": "2500 points added to your account.",                 "type": "POINTS"},
        {"username": "gautam.hazarika",    "title": "Review received",              "message": "Great work recognised by grace.hopper!",             "type": "REVIEW"},
        {"username": "swarup.das",         "title": "Reward redeemed",              "message": "Your Udemy course bundle has been processed.",        "type": "REWARD"},
        {"username": "mrinmoy.kashyap",    "title": "New review",                   "message": "olivia.khan reviewed your QA work.",                 "type": "REVIEW"},
        {"username": "rishav.bora",        "title": "Review received",              "message": "shubrajit.deb recognised your frontend work.",        "type": "REVIEW"},
        {"username": "aminul.islam",       "title": "Welcome to the platform!",     "message": "Your account has been set up. Start earning!",        "type": "SYSTEM"},
        {"username": "bikash.bora",        "title": "Welcome to the platform!",     "message": "You are all set. Explore rewards and recognition.",   "type": "SYSTEM"},
        {"username": "dipam.barman",       "title": "Review received",              "message": "bob.sharma recognised your analytics work.",          "type": "REVIEW"},
        {"username": "frank.das",          "title": "Reward redeemed",              "message": "Your AirPods reward is being processed.",             "type": "REWARD"},
        {"username": "grace.hopper",       "title": "You were recognised!",         "message": "admin.user gave you a top recognition.",              "type": "REVIEW"},
        {"username": "henry.ford",         "title": "Review received",              "message": "carol.nair recognised your architecture work.",       "type": "REVIEW"},
        {"username": "iris.patel",         "title": "Points credited",              "message": "1200 points added from recent review.",               "type": "POINTS"},
        {"username": "james.bond",         "title": "Reward redeemed",              "message": "Your OReilly subscription is active.",                "type": "REWARD"},
        {"username": "kate.miller",        "title": "Review received",              "message": "david.paul recognised your product work.",            "type": "REVIEW"},
        {"username": "leo.king",           "title": "Points credited",              "message": "1100 points added from a review.",                    "type": "POINTS"},
        {"username": "maya.verma",         "title": "Reward redeemed",              "message": "Your Amazon gift card is ready.",                     "type": "REWARD"},
        {"username": "neil.gupta",         "title": "Review received",              "message": "grace.hopper recognised your leadership.",            "type": "REVIEW"},
        {"username": "olivia.khan",        "title": "Welcome to the platform!",     "message": "Start giving and receiving recognition today.",       "type": "SYSTEM"},
        {"username": "peter.sen",          "title": "Welcome to the platform!",     "message": "Your intern account is ready. Start exploring!",      "type": "SYSTEM"},
        {"username": "arijit.banik",       "title": "Review received",              "message": "frank.das recognised your mobile dev skills.",        "type": "REVIEW"},
        {"username": "binit.goswami",      "title": "Review received",              "message": "jane.smith gave you feedback on your first month.",   "type": "REVIEW"},
        {"username": "carol.nair",         "title": "Reward redeemed",              "message": "Your Spotify premium is now active.",                 "type": "REWARD"},
        {"username": "david.paul",         "title": "Reward redeemed",              "message": "Your Ola cab credits have been loaded.",              "type": "REWARD"},
        {"username": "bob.sharma",         "title": "Review received",              "message": "leo.king recognised your product roadmap work.",      "type": "REVIEW"},
        {"username": "admin.user",         "title": "System health check",          "message": "All seeded data loaded successfully.",                "type": "SYSTEM"},
        {"username": "midanka.lahon",      "title": "Points credited",              "message": "2500 points added to your wallet.",                   "type": "POINTS"},
        {"username": "gautam.hazarika",    "title": "Reward redeemed",              "message": "Your Kindle eReader reward is being shipped.",        "type": "REWARD"},
    ]

    for n in notif_data:
        emp_id = emp_map.get(n["username"])
        if not emp_id:
            continue
        await db.notifications.create(data={
            "employee_id": emp_id,
            "title":       n["title"],
            "message":     n["message"],
            "type":        n["type"],
            "is_read":     False,
            "email_sent":  False,
        })

    # =========================================================================
    print("Seed complete!")
    print(f"   Employees:          {len(emp_map)}")
    print(f"   Statuses:           {len(statuses)}")
    print(f"   Dept types:         {len(dept_type_data)}")
    print(f"   Departments:        {len(dept_data)}")
    print(f"   Designations:       {len(designation_data)}")
    print(f"   Roles:              {len(role_data)}")
    print(f"   Txn types:          {len(txn_types)}")
    print(f"   Reward categories:  {len(reward_cat_data)}")
    print(f"   Reward catalog:     {len(catalog_data)}")
    print(f"   Review categories:  {len(review_cat_data)}")
    print(f"   Reward history:     {len(reward_history_data)}")
    print(f"   Notifications:      {len(notif_data)}")

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())