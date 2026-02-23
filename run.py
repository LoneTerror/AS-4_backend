import subprocess

services = [
    ("auth", "src.auth.main:app", 8001),
    ("employees", "src.employees.main:app", 8003),
    ("wallet", "src.wallet.main:app", 8004),
    ("recognition", "src.recognition.main:app", 8005),
    ("rewards", "src.rewards.main:app", 8006),
]

processes = []

for name, app, port in services:
    print(f"Starting {name} on port {port}...")
    p = subprocess.Popen([
        "uvicorn",
        app,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--reload"
    ])
    processes.append(p)

# Keep script alive
for p in processes:
    p.wait()