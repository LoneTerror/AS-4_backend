# test_routes.py — validates auth, authz, and basic 200s across all services
import asyncio
import httpx

AUTH_BASE         = "http://localhost:8001"   # /v1/auth/...
ROLES_BASE        = "http://localhost:8002"   # /v1/roles/..., /v1/route-permissions
EMPLOYEES_BASE    = "http://localhost:8003"   # /v1/employees/..., /v1/notifications/...
WALLET_BASE       = "http://localhost:8004"   # /v1/transactions/..., /v1/wallets/...
RECOGNITION_BASE  = "http://localhost:8005"   # /v1/reviews/..., /v1/review-categories/..., /v1/digest/...
REWARDS_BASE      = "http://localhost:8006"   # /v1/rewards/...
ORGANIZATION_BASE = "http://localhost:8007"   # /v1/org/departments/..., /v1/org/designations/...
ANALYTICS_BASE    = "http://localhost:8008"   # /v1/dashboard/...

PASS = 0
FAIL = 0
SKIP = 0


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def login(username: str, password: str) -> str | None:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(f"{AUTH_BASE}/v1/auth/login",
                                  json={"username": username, "password": password}, timeout=5)
            data = r.json()
            token = data.get("access_token")
            if not token:
                print(f"  ⚠  Login failed for {username}: {data}")
            return token
        except Exception as e:
            print(f"  💥 Login exception for {username}: {e}")
            return None


async def check(client, method, base, path, token=None, expected=200, label=None, **kwargs):
    global PASS, FAIL
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    tag = label or f"{method.upper()} {path}"
    try:
        r = await getattr(client, method)(
            f"{base}{path}", headers=headers, timeout=5, **kwargs
        )
        ok   = r.status_code == expected
        icon = "✅" if ok else "❌"
        print(f"  {icon} [{r.status_code}] {tag}  (expected {expected})")
        if ok:
            PASS += 1
        else:
            FAIL += 1
            try:
                print(f"       ↳ {r.json()}")
            except Exception:
                pass
    except Exception as e:
        print(f"  💥 {method.upper()} {base}{path} — {e}")
        FAIL += 1


async def ping(base: str, label: str) -> bool:
    global SKIP
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"{base}/health", timeout=2)
        return True
    except Exception:
        print(f"  ⚠  {label} unreachable at {base} — skipping its tests")
        SKIP += 1
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    async with httpx.AsyncClient() as client:

        # ── Service health ─────────────────────────────────────────────────────
        print("\n🏥 Checking service availability...")
        svc_up = {
            "auth":         await ping(AUTH_BASE,         "Auth         (8001)"),
            "roles":        await ping(ROLES_BASE,        "Roles        (8002)"),
            "employees":    await ping(EMPLOYEES_BASE,    "Employees    (8003)"),
            "wallet":       await ping(WALLET_BASE,       "Wallet       (8004)"),
            "recognition":  await ping(RECOGNITION_BASE,  "Recognition  (8005)"),
            "rewards":      await ping(REWARDS_BASE,      "Rewards      (8006)"),
            "organization": await ping(ORGANIZATION_BASE, "Organization (8007)"),
            "analytics":    await ping(ANALYTICS_BASE,    "Analytics    (8008)"),
        }

        if not svc_up["auth"]:
            print("\n❌ Auth service is down — cannot log in. Aborting.")
            return

        # ── Login ──────────────────────────────────────────────────────────────
        print("\n🔑 Logging in as test users...")
        admin_token    = await login("admin.user", "Password123!")   # SUPER_ADMIN + HR_ADMIN
        manager_token  = await login("jane.smith", "Password123!")   # MANAGER + EMPLOYEE
        employee_token = await login("john.doe",   "Password123!")   # EMPLOYEE only

        if not all([admin_token, manager_token, employee_token]):
            print("\n❌ One or more logins failed — check credentials/auth service.")
            return

        # =====================================================================
        # 1. AUTH — public endpoints (no token required)
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🔁  AUTH — public endpoints")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        await check(client, "post", AUTH_BASE, "/v1/auth/login",
                    json={"username": "admin.user", "password": "Password123!"},
                    expected=200, label="POST /v1/auth/login  [valid credentials]")
        await check(client, "post", AUTH_BASE, "/v1/auth/login",
                    json={"username": "wrong", "password": "wrong"},
                    expected=401, label="POST /v1/auth/login  [bad credentials → 401]")
        await check(client, "post", AUTH_BASE, "/v1/auth/forgot-password",
                    json={"email": "john.doe@company.com"},
                    expected=200, label="POST /v1/auth/forgot-password  [always 200]")

        # =====================================================================
        # 2. 401 — NO TOKEN
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🚫  401 — No token  (missing Authorization header)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if svc_up["employees"]:
            await check(client, "get",  EMPLOYEES_BASE, "/v1/employees",                    expected=401)
            await check(client, "get",  EMPLOYEES_BASE, "/v1/notifications",                expected=401)
        if svc_up["roles"]:
            await check(client, "get",  ROLES_BASE, "/v1/roles",                            expected=401)
            await check(client, "get",  ROLES_BASE, "/v1/route-permissions",                expected=401)
        if svc_up["recognition"]:
            await check(client, "get",  RECOGNITION_BASE, "/v1/reviews",                    expected=401)
            await check(client, "get",  RECOGNITION_BASE, "/v1/review-categories",          expected=401)
            await check(client, "get",  RECOGNITION_BASE, "/v1/digest",                     expected=401)
        if svc_up["rewards"]:
            await check(client, "get",  REWARDS_BASE, "/v1/rewards/catalog",                expected=401)
            await check(client, "get",  REWARDS_BASE, "/v1/rewards/history/me",             expected=401)
        if svc_up["organization"]:
            await check(client, "get",  ORGANIZATION_BASE, "/v1/org/departments",           expected=401)
            await check(client, "get",  ORGANIZATION_BASE, "/v1/org/designations",          expected=401)
            await check(client, "get",  ORGANIZATION_BASE, "/v1/org/department-types",      expected=401)
        if svc_up["analytics"]:
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/recent-reviews",     expected=401)
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/leaderboard",        expected=401)
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/platform-stats",     expected=401)
        if svc_up["wallet"]:
            await check(client, "get",  WALLET_BASE, "/v1/transactions",                    expected=401,
                        params={"wallet_id": "00000000-0000-0000-0000-000000000000"})
            await check(client, "get",  WALLET_BASE, "/v1/transactions/types",              expected=401)
            await check(client, "get",  WALLET_BASE, "/v1/wallets/employees/test",          expected=401)

        # =====================================================================
        # 3. 403 — WRONG ROLE
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🔒  403 — Wrong role")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # ── EMPLOYEE trying routes that need MANAGER+ or HR_ADMIN+ ────────────
        if svc_up["employees"]:
            await check(client, "get",  EMPLOYEES_BASE, "/v1/employees",
                        token=employee_token, expected=403,
                        label="GET  /v1/employees  [EMPLOYEE → needs MANAGER+]")
            await check(client, "post", EMPLOYEES_BASE, "/v1/employees",
                        token=employee_token, expected=403,
                        label="POST /v1/employees  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"username": "x", "email": "x@x.com", "password": "x"})
        if svc_up["roles"]:
            await check(client, "get",  ROLES_BASE, "/v1/roles",
                        token=employee_token, expected=403,
                        label="GET  /v1/roles  [EMPLOYEE → needs HR_ADMIN+]")
            await check(client, "post", ROLES_BASE, "/v1/roles",
                        token=employee_token, expected=403,
                        label="POST /v1/roles  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"role_name": "TEST", "role_code": "TEST"})
            await check(client, "post", ROLES_BASE, "/v1/roles/assign",
                        token=employee_token, expected=403,
                        label="POST /v1/roles/assign  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"employee_id": "00000000-0000-0000-0000-000000000000",
                              "role_id": "00000000-0000-0000-0000-000000000000"})
            await check(client, "get",  ROLES_BASE, "/v1/route-permissions",
                        token=employee_token, expected=403,
                        label="GET  /v1/route-permissions  [EMPLOYEE → needs HR_ADMIN+]")
        if svc_up["analytics"]:
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/recent-reviews",
                        token=employee_token, expected=403,
                        label="GET  /v1/dashboard/recent-reviews  [EMPLOYEE → needs MANAGER+]")
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/leaderboard",
                        token=employee_token, expected=403,
                        label="GET  /v1/dashboard/leaderboard  [EMPLOYEE → needs MANAGER+]")
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/platform-stats",
                        token=employee_token, expected=403,
                        label="GET  /v1/dashboard/platform-stats  [EMPLOYEE → needs HR_ADMIN+]")
        if svc_up["rewards"]:
            await check(client, "post", REWARDS_BASE, "/v1/rewards/catalog",
                        token=employee_token, expected=403,
                        label="POST /v1/rewards/catalog  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"reward_name": "x", "reward_code": "x", "description": "x",
                              "default_points": 1, "min_points": 1, "max_points": 1,
                              "category_id": "00000000-0000-0000-0000-000000000000"})
            await check(client, "post", REWARDS_BASE, "/v1/rewards/categories",
                        token=employee_token, expected=403,
                        label="POST /v1/rewards/categories  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"category_name": "x", "category_code": "x"})
            await check(client, "get",  REWARDS_BASE, "/v1/rewards/history",
                        token=employee_token, expected=403,
                        label="GET  /v1/rewards/history  [EMPLOYEE → needs MANAGER+]")
        if svc_up["recognition"]:
            await check(client, "post", RECOGNITION_BASE, "/v1/reviews",
                        token=employee_token, expected=403,
                        label="POST /v1/reviews  [EMPLOYEE → needs MANAGER+]",
                        json={"receiver_id": "00000000-0000-0000-0000-000000000000",
                              "rating": 3, "category_ids": [], "comment": "test"})
            await check(client, "post", RECOGNITION_BASE, "/v1/review-categories",
                        token=employee_token, expected=403,
                        label="POST /v1/review-categories  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"category_code": "X", "category_name": "X", "multiplier": 1.0})
            await check(client, "get",  RECOGNITION_BASE, "/v1/digest",
                        token=employee_token, expected=403,
                        label="GET  /v1/digest  [EMPLOYEE → needs MANAGER+]")
        if svc_up["organization"]:
            await check(client, "post", ORGANIZATION_BASE, "/v1/org/departments",
                        token=employee_token, expected=403,
                        label="POST /v1/org/departments  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"department_name": "x", "department_code": "x"})
            await check(client, "post", ORGANIZATION_BASE, "/v1/org/designations",
                        token=employee_token, expected=403,
                        label="POST /v1/org/designations  [EMPLOYEE → needs HR_ADMIN+]",
                        json={"designation_name": "x", "designation_code": "x"})
        if svc_up["wallet"]:
            await check(client, "post", WALLET_BASE, "/v1/wallets/credit-from-review",
                        token=employee_token, expected=403,
                        label="POST /v1/wallets/credit-from-review  [EMPLOYEE → needs HR_ADMIN+]",
                        params={"review_id": "00000000-0000-0000-0000-000000000000"})

        # ── MANAGER trying HR_ADMIN-only routes ────────────────────────────────
        if svc_up["roles"]:
            await check(client, "post", ROLES_BASE, "/v1/roles",
                        token=manager_token, expected=403,
                        label="POST /v1/roles  [MANAGER → needs HR_ADMIN+]",
                        json={"role_name": "TEST", "role_code": "TEST"})
            await check(client, "post", ROLES_BASE, "/v1/roles/assign",
                        token=manager_token, expected=403,
                        label="POST /v1/roles/assign  [MANAGER → needs HR_ADMIN+]",
                        json={"employee_id": "00000000-0000-0000-0000-000000000000",
                              "role_id": "00000000-0000-0000-0000-000000000000"})
        if svc_up["analytics"]:
            await check(client, "get",  ANALYTICS_BASE, "/v1/dashboard/platform-stats",
                        token=manager_token, expected=403,
                        label="GET  /v1/dashboard/platform-stats  [MANAGER → needs HR_ADMIN+]")
        if svc_up["rewards"]:
            await check(client, "post", REWARDS_BASE, "/v1/rewards/catalog",
                        token=manager_token, expected=403,
                        label="POST /v1/rewards/catalog  [MANAGER → needs HR_ADMIN+]",
                        json={"reward_name": "x", "reward_code": "x", "description": "x",
                              "default_points": 1, "min_points": 1, "max_points": 1,
                              "category_id": "00000000-0000-0000-0000-000000000000"})
        if svc_up["employees"]:
            await check(client, "post", EMPLOYEES_BASE, "/v1/employees",
                        token=manager_token, expected=403,
                        label="POST /v1/employees  [MANAGER → needs HR_ADMIN+]",
                        json={"username": "x", "email": "x@x.com", "password": "x"})
        if svc_up["organization"]:
            await check(client, "post", ORGANIZATION_BASE, "/v1/org/departments",
                        token=manager_token, expected=403,
                        label="POST /v1/org/departments  [MANAGER → needs HR_ADMIN+]",
                        json={"department_name": "x", "department_code": "x"})

        # =====================================================================
        # 4. 200 — SUPER_ADMIN  (bypasses all permission checks)
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("👑  SUPER_ADMIN (admin.user) — bypasses all permission checks")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if svc_up["employees"]:
            await check(client, "get", EMPLOYEES_BASE, "/v1/employees",
                        token=admin_token, label="GET /v1/employees")
            await check(client, "get", EMPLOYEES_BASE, "/v1/employees/110e8400-e29b-41d4-a716-446655440000",
                        token=admin_token, label="GET /v1/employees/{id}")
            await check(client, "get", EMPLOYEES_BASE, "/v1/notifications",
                        token=admin_token, label="GET /v1/notifications")
            await check(client, "get", EMPLOYEES_BASE, "/v1/notifications/unread-count",
                        token=admin_token, label="GET /v1/notifications/unread-count")
        if svc_up["roles"]:
            await check(client, "get", ROLES_BASE, "/v1/roles",
                        token=admin_token, label="GET /v1/roles")
            await check(client, "get", ROLES_BASE, "/v1/roles/employees",
                        token=admin_token, label="GET /v1/roles/employees")
            await check(client, "get", ROLES_BASE, "/v1/route-permissions",
                        token=admin_token, label="GET /v1/route-permissions")
        if svc_up["recognition"]:
            await check(client, "get", RECOGNITION_BASE, "/v1/reviews",
                        token=admin_token, label="GET /v1/reviews")
            await check(client, "get", RECOGNITION_BASE, "/v1/review-categories",
                        token=admin_token, label="GET /v1/review-categories")
            await check(client, "get", RECOGNITION_BASE, "/v1/digest",
                        token=admin_token, label="GET /v1/digest")
        if svc_up["rewards"]:
            await check(client, "get", REWARDS_BASE, "/v1/rewards/catalog",
                        token=admin_token, label="GET /v1/rewards/catalog")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/categories",
                        token=admin_token, label="GET /v1/rewards/categories")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/history",
                        token=admin_token, label="GET /v1/rewards/history")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/history/me",
                        token=admin_token, label="GET /v1/rewards/history/me")
        if svc_up["organization"]:
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/departments",
                        token=admin_token, label="GET /v1/org/departments")
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/designations",
                        token=admin_token, label="GET /v1/org/designations")
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/department-types",
                        token=admin_token, label="GET /v1/org/department-types")
        if svc_up["analytics"]:
            await check(client, "get", ANALYTICS_BASE, "/v1/dashboard/recent-reviews",
                        token=admin_token, label="GET /v1/dashboard/recent-reviews")
            await check(client, "get", ANALYTICS_BASE, "/v1/dashboard/leaderboard",
                        token=admin_token, label="GET /v1/dashboard/leaderboard")
            await check(client, "get", ANALYTICS_BASE, "/v1/dashboard/platform-stats",
                        token=admin_token, label="GET /v1/dashboard/platform-stats")
        if svc_up["wallet"]:
            await check(client, "get", WALLET_BASE, "/v1/transactions/types",
                        token=admin_token, label="GET /v1/transactions/types")
            await check(client, "get", WALLET_BASE, "/v1/wallets/employees/110e8400-e29b-41d4-a716-446655440000",
                        token=admin_token, label="GET /v1/wallets/employees/{employee_id}")

        # =====================================================================
        # 5. 200 — MANAGER (jane.smith)  roles: MANAGER + EMPLOYEE
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("👔  MANAGER (jane.smith) — roles: MANAGER + EMPLOYEE")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if svc_up["employees"]:
            await check(client, "get", EMPLOYEES_BASE, "/v1/employees",
                        token=manager_token, label="GET /v1/employees  [MANAGER ✓]")
            await check(client, "get", EMPLOYEES_BASE, "/v1/employees/550e8400-e29b-41d4-a716-446655440000",
                        token=manager_token, label="GET /v1/employees/{id}  [MANAGER ✓]")
            await check(client, "get", EMPLOYEES_BASE, "/v1/notifications",
                        token=manager_token, label="GET /v1/notifications  [EMPLOYEE ✓]")
        if svc_up["recognition"]:
            await check(client, "get", RECOGNITION_BASE, "/v1/reviews",
                        token=manager_token, label="GET /v1/reviews  [MANAGER ✓]")
            await check(client, "get", RECOGNITION_BASE, "/v1/review-categories",
                        token=manager_token, label="GET /v1/review-categories  [MANAGER ✓]")
            await check(client, "get", RECOGNITION_BASE, "/v1/digest",
                        token=manager_token, label="GET /v1/digest  [MANAGER ✓]")
        if svc_up["analytics"]:
            await check(client, "get", ANALYTICS_BASE, "/v1/dashboard/recent-reviews",
                        token=manager_token, label="GET /v1/dashboard/recent-reviews  [MANAGER ✓]")
            await check(client, "get", ANALYTICS_BASE, "/v1/dashboard/leaderboard",
                        token=manager_token, label="GET /v1/dashboard/leaderboard  [MANAGER ✓]")
        if svc_up["organization"]:
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/departments",
                        token=manager_token, label="GET /v1/org/departments  [MANAGER ✓]")
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/designations",
                        token=manager_token, label="GET /v1/org/designations  [MANAGER ✓]")
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/department-types",
                        token=manager_token, label="GET /v1/org/department-types  [EMPLOYEE ✓]")
        if svc_up["rewards"]:
            await check(client, "get", REWARDS_BASE, "/v1/rewards/catalog",
                        token=manager_token, label="GET /v1/rewards/catalog  [EMPLOYEE ✓]")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/categories",
                        token=manager_token, label="GET /v1/rewards/categories  [EMPLOYEE ✓]")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/history/me",
                        token=manager_token, label="GET /v1/rewards/history/me  [EMPLOYEE ✓]")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/history",
                        token=manager_token, label="GET /v1/rewards/history  [MANAGER ✓]")
        if svc_up["wallet"]:
            await check(client, "get", WALLET_BASE, "/v1/transactions/types",
                        token=manager_token, label="GET /v1/transactions/types  [EMPLOYEE ✓]")

        # =====================================================================
        # 6. 200 — EMPLOYEE (john.doe)  role: EMPLOYEE only
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("👤  EMPLOYEE (john.doe) — role: EMPLOYEE only")
        print("    Note: /v1/reviews returns only own reviews (service-layer filter)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if svc_up["recognition"]:
            await check(client, "get", RECOGNITION_BASE, "/v1/reviews",
                        token=employee_token, label="GET /v1/reviews  [EMPLOYEE ✓ — own only]")
            await check(client, "get", RECOGNITION_BASE, "/v1/review-categories",
                        token=employee_token, label="GET /v1/review-categories  [EMPLOYEE ✓]")
        if svc_up["rewards"]:
            await check(client, "get", REWARDS_BASE, "/v1/rewards/catalog",
                        token=employee_token, label="GET /v1/rewards/catalog  [EMPLOYEE ✓]")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/categories",
                        token=employee_token, label="GET /v1/rewards/categories  [EMPLOYEE ✓]")
            await check(client, "get", REWARDS_BASE, "/v1/rewards/history/me",
                        token=employee_token, label="GET /v1/rewards/history/me  [EMPLOYEE ✓]")
        if svc_up["organization"]:
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/departments",
                        token=employee_token, label="GET /v1/org/departments  [EMPLOYEE ✓]")
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/designations",
                        token=employee_token, label="GET /v1/org/designations  [EMPLOYEE ✓]")
            await check(client, "get", ORGANIZATION_BASE, "/v1/org/department-types",
                        token=employee_token, label="GET /v1/org/department-types  [EMPLOYEE ✓]")
        if svc_up["employees"]:
            await check(client, "get", EMPLOYEES_BASE, "/v1/notifications",
                        token=employee_token, label="GET /v1/notifications  [EMPLOYEE ✓]")
            await check(client, "get", EMPLOYEES_BASE, "/v1/notifications/unread-count",
                        token=employee_token, label="GET /v1/notifications/unread-count  [EMPLOYEE ✓]")
        if svc_up["wallet"]:
            await check(client, "get", WALLET_BASE, "/v1/transactions/types",
                        token=employee_token, label="GET /v1/transactions/types  [EMPLOYEE ✓]")

        # =====================================================================
        # 7. PATCH /v1/route-permissions (soft-delete)
        # =====================================================================
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("🔧  PATCH /v1/route-permissions (soft-delete, HR_ADMIN+ only)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if svc_up["roles"]:
            await check(client, "patch", ROLES_BASE, "/v1/route-permissions",
                        token=admin_token, expected=404,
                        label="PATCH /v1/route-permissions  [SUPER_ADMIN, 404 = authz passed]",
                        json={"route_key": "GET:/v1/nonexistent",
                              "role_id": "00000000-0000-0000-0000-000000000000"})
            await check(client, "patch", ROLES_BASE, "/v1/route-permissions",
                        token=employee_token, expected=403,
                        label="PATCH /v1/route-permissions  [EMPLOYEE → 403]",
                        json={"route_key": "GET:/v1/nonexistent",
                              "role_id": "00000000-0000-0000-0000-000000000000"})

        # ── Summary ────────────────────────────────────────────────────────────
        total = PASS + FAIL
        services_down = sum(1 for up in svc_up.values() if not up)
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"📊  Results:  ✅ {PASS}/{total} passed   ❌ {FAIL}/{total} failed   ⚠️  {SKIP} services skipped")
        if services_down:
            down_names = [name for name, up in svc_up.items() if not up]
            print(f"    Services down: {', '.join(down_names)}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")


asyncio.run(main())