"""
diagnostic.py — drop in analytics service root, run: python diagnostic.py
Tests every layer and prints exactly where it fails.
"""
import os, sys, asyncio, traceback, json
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

P, F, W = "✅", "❌", "⚠️ "

async def main():
    from src.prisma.client import db
    await db.connect()
    print("\n🔌 Connected\n")

    # 1 ── raw counts ──────────────────────────────────────────
    print("=" * 55)
    print("1. RAW ROW COUNTS")
    print("=" * 55)
    for t in ["departments","employees","wallets","transaction_types",
              "reviews","reward_history","transactions"]:
        try:
            r = await db.execute_raw(f"SELECT COUNT(*)::int AS n FROM {t}")
            print(f"  {P} {t:<28} {r[0]['n']}")
        except Exception as e:
            print(f"  {F} {t:<28} {e}")

    # 2 ── departments via Prisma ──────────────────────────────
    print("\n" + "=" * 55)
    print("2. db.departments.find_many()")
    print("=" * 55)
    try:
        depts = await db.departments.find_many(order={"department_name": "asc"})
        print(f"  {P} {len(depts)} departments")
        for d in depts:
            print(f"     id={d.department_id!r}  type={type(d.department_id).__name__}  name={d.department_name}")
    except Exception as e:
        print(f"  {F} {e}"); traceback.print_exc(); await db.disconnect(); return

    # 3 ── employees per dept — passing native object ──────────
    print("\n" + "=" * 55)
    print("3. get_employees_in_department(dept)  [native object]")
    print("=" * 55)
    for dept in depts:
        try:
            emps = await db.employees.find_many(
                where={"department_id": dept.department_id},   # native UUID
                include={"designations_employees_designation_idTodesignations": True},
            )
            print(f"  {P} {dept.department_name}: {len(emps)} employees")
            for e in emps:
                desig = getattr(e, "designations_employees_designation_idTodesignations", None)
                print(f"       {e.username:<28} desig={desig.designation_name if desig else 'MISSING'}")
        except Exception as e:
            print(f"  {F} {dept.department_name}: {e}"); traceback.print_exc()

    # 4 ── wallet per employee — native object ─────────────────
    print("\n" + "=" * 55)
    print("4. get_wallet_for_employee(emp)  [native object]")
    print("=" * 55)
    try:
        all_emps = await db.employees.find_many()
        for emp in all_emps:
            w = await db.wallets.find_first(where={"employee_id": emp.employee_id})
            status = f"wallet_id={w.wallet_id!r}  pts={w.total_earned_points}" if w else "NO WALLET"
            icon = P if w else F
            print(f"  {icon} {emp.username:<28} {status}")
    except Exception as e:
        print(f"  {F} {e}"); traceback.print_exc()

    # 5 ── review counts — native object ───────────────────────
    print("\n" + "=" * 55)
    print("5. review count per employee  [native object]")
    print("=" * 55)
    try:
        all_emps = await db.employees.find_many()
        for emp in all_emps:
            n = await db.reviews.count(where={"receiver_id": emp.employee_id})
            print(f"  {P} {emp.username:<28} reviews={n}")
    except Exception as e:
        print(f"  {F} {e}"); traceback.print_exc()

    # 6 ── full service call ───────────────────────────────────
    print("\n" + "=" * 55)
    print("6. get_teams_summary()  [full service]")
    print("=" * 55)
    try:
        from src.analytics.service import get_teams_summary
        summaries = await get_teams_summary()
        print(f"  {P} Returned {len(summaries)} summaries:")
        for s in summaries:
            print(f"     {s.department_name:<28} members={s.total_members}  pts={s.total_points}  score={s.avg_performance_score}")
    except Exception as e:
        print(f"  {F} {type(e).__name__}: {e}"); traceback.print_exc()

    # 7 ── pydantic serialisation ──────────────────────────────
    print("\n" + "=" * 55)
    print("7. Pydantic serialisation")
    print("=" * 55)
    try:
        from src.analytics.service import get_teams_summary
        summaries = await get_teams_summary()
        out = json.dumps([s.model_dump() for s in summaries], default=str, indent=2)
        print(f"  {P} OK:\n{out}")
    except Exception as e:
        print(f"  {F} {type(e).__name__}: {e}"); traceback.print_exc()

    await db.disconnect()
    print("\n" + "=" * 55)
    print("DONE")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    asyncio.run(main())