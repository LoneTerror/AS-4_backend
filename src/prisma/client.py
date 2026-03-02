import os
from prisma import Prisma

# Each of the 7 services imports this module and calls db.connect() on startup.
# Without a connection limit, each service spawns Prisma's default pool (10),
# giving you 7 × 10 = 70 simultaneous connections — enough to crash most
# managed DB tiers immediately at boot.
#
# connection_limit=3  → 7 × 3 = 21 total connections (safe for all DB tiers)
# pool_timeout=15     → wait up to 15s for a free slot before raising an error
#                        instead of hanging forever
# connect_timeout=10  → fail fast if the DB host is unreachable

_BASE_URL = os.environ["DATABASE_URL"]

# Avoid double-appending params if DATABASE_URL already has a query string
_SEP = "&" if "?" in _BASE_URL else "?"
_DB_URL = f"{_BASE_URL}{_SEP}connection_limit=3&pool_timeout=15&connect_timeout=10"

db = Prisma(datasource={"url": _DB_URL})