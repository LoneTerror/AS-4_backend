# quick_check.py — drop in project root, run once
import asyncio, os
from pathlib import Path

env = Path(".env")
if env.exists():
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

from src.prisma.client import db

async def main():
    await db.connect()
    logs = await db.audit_log.find_many(
        take=3,
        order={"performed_at": "desc"},
        include={"employees": True},
    )
    for log in logs:
        print(f"performed_by={log.performed_by}  employees={log.employees}")
        if log.employees:
            print(f"  → username={log.employees.username}")
        else:
            print(f"  → employees is None — FK broken or employee deleted")
    await db.disconnect()

asyncio.run(main())