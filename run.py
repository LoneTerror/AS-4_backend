import subprocess
import time
import sys
import os
import urllib.request
from pathlib import Path

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
    print("Loaded environment from {}".format(env_file))
else:
    print("Warning: no .env found")

services = [
    ("auth",         "src.auth.main:app",           8001),
    ("roles",    "src.roles.main:app",              8002),
    ("employees",    "src.employees.main:app",      8003),
    ("wallets",       "src.wallet.main:app",         8004),
    ("recognitions",  "src.recognition.main:app",    8005),
    ("rewards",      "src.rewards.main:app",        8006),
    ("organizations", "src.organization.main:app",   8007),
    ("analytics",    "src.analytics.main:app",      8008),
    
]

STAGGER_SECONDS = 3
HEALTH_TIMEOUT = 20

def wait_for_service(name, port, timeout):
    url = "http://localhost:{}/health".format(port)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False

processes = []

for name, app, port in services:
    print("Starting {} on port {}...".format(name, port))
    p = subprocess.Popen([
        "uvicorn", app,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--reload"
    ])
    processes.append((name, p, port))
    healthy = wait_for_service(name, port, HEALTH_TIMEOUT)
    if healthy:
        print("  {} is up".format(name))
    else:
        print("  {} didn't respond within {}s — continuing anyway".format(name, HEALTH_TIMEOUT))
    time.sleep(STAGGER_SECONDS)

print("\nAll services launched.\n")
for name, _, port in processes:
    print("  {:<15} -> http://localhost:{}/aabhar/v1/{}/docs".format(name, port, name))

try:
    while True:
        for name, p, port in processes:
            ret = p.poll()
            if ret is not None:
                print("\n{} exited with code {}.".format(name, ret))
                for _, other, _ in processes:
                    other.terminate()
                sys.exit(ret)
        time.sleep(5)
except KeyboardInterrupt:
    print("\nShutting down...")
    for _, p, _ in processes:
        p.terminate()
    for _, p, _ in processes:
        p.wait()
    print("All services stopped.")