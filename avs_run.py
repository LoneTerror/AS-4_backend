import subprocess
import webbrowser
import socket
import time
import sys

# Configuration: (Name, App Module, Port, Docs Path)
services = [
    ("auth", "src.auth.main:app", 8001, "/v1/docs"),
    # ("notifications", "src.notifications.main:app", 8002, "/v1/docs"),
    ("employees", "src.employees.main:app", 8003, "/v1/docs"),
    ("wallet", "src.wallet.main:app", 8004, "/v1/docs"),
    ("recognition", "src.recognition.main:app", 8005, "/v1/docs"),
    ("rewards", "src.rewards.main:app", 8006, "/v1/docs"),
    ("organization", "src.organization.main:app", 8007, "/v1/docs"),
    ("analytics", "src.analytics.main:app", 8008, "/v1/docs"),
]

def wait_for_service(port, timeout=10):
    """Wait for a local port to become active."""
    start_time = time.time()
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout):
            if time.time() - start_time > timeout:
                return False
            time.sleep(0.3)

processes = []

print("🚀 Starting Microservices Ecosystem...")

for name, app, port, path in services:
    print(f"📦 Launching {name} on http://127.0.0.1:{port}...")
    
    # Start Uvicorn
    p = subprocess.Popen([
        "uvicorn",
        app,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--reload"
    ])
    processes.append(p)

    # Industry Standard: Health check before opening browser
    if wait_for_service(port):
        url = f"http://127.0.0.1:{port}{path}"
        webbrowser.open(url)
    else:
        print(f"⚠️ Warning: {name} took too long to start. Browser not opened.")

try:
    # Keep script alive to maintain subprocesses
    print("\n✅ All services are running. Press Ctrl+C to stop all.")
    for p in processes:
        p.wait()
except KeyboardInterrupt:
    print("\n🛑 Shutting down all services...")
    for p in processes:
        p.terminate()
    sys.exit(0)