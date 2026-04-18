import subprocess
import time
import sys
import os
import urllib.request
import signal
from pathlib import Path
from threading import Thread

# ---------- Load .env ----------
env_file = Path(__file__).parent / ".env"

if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()

        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]

        os.environ.setdefault(key, val)

    print(f"Loaded environment from {env_file}")
else:
    print("Warning: no .env found")

# ---------- Services ----------
services = [
    ("auth",         "src.auth.main:app",         8001),
    ("roles",        "src.roles.main:app",         8002),
    ("employees",    "src.employees.main:app",     8003),
    ("wallet",       "src.wallet.main:app",        8004),
    ("recognition",  "src.recognition.main:app",   8005),
    ("rewards",      "src.rewards.main:app",        8006),
    ("organization", "src.organization.main:app",  8007),
    ("analytics",    "src.analytics.main:app",     8008),
]

# Default timeout for all services.
# Employees gets a longer override because it runs route-registry DB lookup,
# starts two background workers, and connects to both Redis and Slack on startup
# — it legitimately takes 2-3x longer than lightweight services.
DEFAULT_HEALTH_TIMEOUT = 60

HEALTH_TIMEOUT_OVERRIDES: dict[str, int] = {
    "employees": 90,   # workers + route registry + Redis + Slack init
}

# How long to wait after launching ALL processes before polling health.
# FIX: was 3s — not enough for employees (Prisma engine + worker init ~4-5s).
# 8s gives every service enough time to reach its first yield before we poll.
INITIAL_WAIT_SECONDS = 8

processes = []


# ---------- Health Check ----------
def wait_for_service(name: str, port: int, timeout: int) -> bool:
    url = f"http://localhost:{port}/health"
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    print(f"  ✓  {name:<15} healthy")
                    return True
        except Exception:
            pass

        time.sleep(1)

    print(f"  ⚠  {name:<15} health check timed out after {timeout}s")
    return False


# ---------- Start Services ----------
print("\n🚀 Launching services...\n")

for name, app, port in services:
    print(f"  Starting {name} on port {port}...")

    p = subprocess.Popen(
        [
            "uvicorn",
            app,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--reload"
        ],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )

    processes.append((name, p, port))

# FIX: Give all uvicorn processes enough time to spawn their worker processes
# and begin lifespan execution before we start polling.
# 3s was too short — employees (and sometimes rewards) weren't ready for the
# first health poll, causing a false timeout even though they started fine.
print(f"\n  ⏱  Waiting {INITIAL_WAIT_SECONDS}s for processes to initialise...\n")
time.sleep(INITIAL_WAIT_SECONDS)


# ---------- Parallel Health Checks ----------
print("\n⏳ Waiting for services to become healthy...\n")

results: dict[str, bool] = {}


def _check(name, port, timeout):
    results[name] = wait_for_service(name, port, timeout)


threads = []

for name, p, port in processes:
    timeout = HEALTH_TIMEOUT_OVERRIDES.get(name, DEFAULT_HEALTH_TIMEOUT)
    t = Thread(target=_check, args=(name, port, timeout), daemon=True)
    t.start()
    threads.append(t)

for t in threads:
    t.join()


# ---------- Summary ----------
healthy   = [n for n, ok in results.items() if ok]
unhealthy = [n for n, ok in results.items() if not ok]

print(f"\n✅ {len(healthy)}/{len(services)} services healthy:\n")

for name, _, port in services:
    status = "✓" if results.get(name) else "⚠"
    print(f"  {status}  {name:<15} -> http://localhost:{port}/aabhar/v1/docs")

if unhealthy:
    print(f"\n⚠ Timed-out services ({', '.join(unhealthy)}) may still be starting.\n")


# ---------- Monitor Processes ----------
print("\n👀 Monitoring processes (Ctrl+C to stop all)...\n")

try:
    while True:
        for name, p, port in processes:
            ret = p.poll()

            if ret is not None and ret != 0:
                print(f"\n❌ {name} exited unexpectedly with code {ret}")

                print("Shutting down all services...\n")

                for _, proc, _ in processes:
                    try:
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    except Exception:
                        proc.terminate()

                for _, proc, _ in processes:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()

                sys.exit(ret)

        time.sleep(3)

except KeyboardInterrupt:
    print("\n🛑 Shutting down services...\n")

    for _, p, _ in processes:
        try:
            p.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception:
            p.terminate()

    for _, p, _ in processes:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()

    print("✅ All services stopped.")