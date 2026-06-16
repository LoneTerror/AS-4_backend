import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ==========================================
# 1. ENVIRONMENT CONFIGURATION (.env)
# ==========================================
# Locate the .env file in the same directory as this script
env_file = Path(__file__).parent / ".env"

if env_file.exists():
    # Read the file line by line to extract configuration key-value pairs
    for line in env_file.read_text().splitlines():
        line = line.strip()
        # Skip empty lines, comments, or malformed entries
        if not line or line.startswith("#") or "=" not in line:
            continue
            
        # Split only at the first '=' to handle values containing equal signs
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        
        # Strip wrapping single or double quotes if present around values
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
            
        # Set environment variable safely if it does not already exist
        os.environ.setdefault(key, val)
    print(f"Loaded environment from {env_file}")
else:
    print("Warning: no .env found")

# ==========================================
# 2. RUNTIME CONFIGURATION & CONSTANTS
# ==========================================
# Defined list of services to manage. 
# Schema format: (Service Name, App Target Path, Local Port, API URL Slug)
SERVICES = [
    ("auth", "src.auth.main:app", 8001, "auth"),
    ("roles", "src.roles.main:app", 8002, "roles"),
    ("employees", "src.employees.main:app", 8003, "employees"),
    ("wallet", "src.wallet.main:app", 8004, "wallets"),
    ("recognition", "src.recognition.main:app", 8005, "recognitions"),
    ("rewards", "src.rewards.main:app", 8006, "rewards"),
    ("organization", "src.organization.main:app", 8007, "organizations"),
    ("analytics", "src.analytics.main:app", 8008, "analytics"),
]

# Health check boundaries (in seconds)
DEFAULT_HEALTH_TIMEOUT = 60
HEALTH_TIMEOUT_OVERRIDES = {"employees": 90}  # Overridden due to heavy startup worker initialisation

# Windows-specific process flags. 'CREATE_NEW_PROCESS_GROUP' ensures that Ctrl+C 
# in the console triggers clean, manageable signal breaks instead of hard kills.
PO_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0

# ==========================================
# 3. HEALTH CHECK WORKER (THREAD-SAFE)
# ==========================================
def wait_for_service(name: str, port: int, timeout: int) -> tuple[str, bool]:
    """
    Repeatedly pings a microservice health endpoint until it responds with a 200 OK
    or hits the predefined timeout ceiling.
    """
    url = f"http://localhost:{port}/health"
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        try:
            # Short 1.5-second socket timeout to prevent a lagging endpoint from stalling the thread
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    print(f" ✓ {name:<15} healthy")
                    return name, True
        except Exception:
            # Any HTTP Error or Connection Error means the service is still booting up
            pass
        time.sleep(1)
        
    print(f" ⚠ {name:<15} health check timed out after {timeout}s")
    return name, False

# ==========================================
# 4. TEARDOWN ENGINE (PROCESS SHUTDOWN)
# ==========================================
def shutdown_all_services(running_processes):
    """
    Iterates through all launched subprocesses to send polite termination signals, 
    falling back to aggressive kills if they ignore the request.
    """
    print("\n🛑 Shutting down all services gracefully...")
    
    # Step 4a: Send OS-compatible termination triggers
    for name, proc, _ in running_processes:
        try:
            if os.name == 'nt':
                # Windows standard for process groups
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                # Linux / macOS standard
                proc.terminate()
        except Exception:
            pass

    # Step 4b: Wait for clean exit, force kill if frozen
    for name, proc, _ in running_processes:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            print(f" 💥 Force killing unresponsive service: {name}")
            try:
                proc.kill()
            except Exception:
                pass
    print("✅ All services stopped.")

# ==========================================
# 5. MAIN CORE EXECUTION FLOW
# ==========================================
def main():
    # Setup and parse Command Line Arguments (CLI)
    parser = argparse.ArgumentParser(description="FastAPI Local Microservices Orchestrator Layout")
    parser.add_argument(
        "--docs", 
        action="store_true", 
        help="Automatically open all local OpenAPI documentation endpoints in your default browser."
    )
    args = parser.parse_args()

    processes = []
    print("\n🚀 Launching services...\n")
    
    try:
        # Step 5a: Spin up all services sequentially using Uvicorn
        for name, app, port, _ in SERVICES:
            print(f" Starting {name} on port {port}...")
            p = subprocess.Popen(
                ["uvicorn", app, "--host", "0.0.0.0", "--port", str(port), "--reload"],
                creationflags=PO_FLAGS
            )
            # Track process objects for monitoring and teardown
            processes.append((name, p, port))

        print("\n⏳ Monitoring startup health (parallel checks)...")
        results = {}
        
        # Step 5b: Execute parallel health checks using an optimized ThreadPoolExecutor.
        # This replaces static waits. As soon as a service is ready, it's marked healthy.
        with ThreadPoolExecutor(max_workers=len(processes)) as executor:
            futures = []
            for name, _, port, _ in SERVICES:
                timeout = HEALTH_TIMEOUT_OVERRIDES.get(name, DEFAULT_HEALTH_TIMEOUT)
                futures.append(executor.submit(wait_for_service, name, port, timeout))
            
            # Gather worker results asynchronously as they complete
            for future in as_completed(futures):
                name, is_healthy = future.result()
                results[name] = is_healthy

        # Step 5c: Display Status Summaries & open URLs if requested
        healthy = [n for n, ok in results.items() if ok]
        unhealthy = [n for n, ok in results.items() if not ok]
        
        print(f"\n📊 Summary: {len(healthy)}/{len(SERVICES)} services are live.")
        for name, _, port, slug in SERVICES:
            status = "✓" if results.get(name) else "⚠"
            doc_url = f"http://localhost:{port}/aabhar/v1/{slug}/docs"
            print(f"  {status} {name:<15} -> {doc_url}")
            
            # If '--docs' flag was called, trigger cross-platform browser opening mechanism
            if args.docs:
                webbrowser.open(doc_url)
                
        if args.docs:
            print("\n🌐 Opened updated documentation tabs in your default system browser.")

        if unhealthy:
            print(f"\n⚠ Warning: ({', '.join(unhealthy)}) failed initial health checks but will remain active.")

        # Step 5d: Continuous loop to ensure active processes don't crash behind the scenes
        print("\n👀 Monitoring processes (Ctrl+C to stop all)...\n")
        while True:
            for name, p, port in processes:
                ret = p.poll()  # Non-blocking status check on active PID
                if ret is not None and ret != 0:
                    print(f"\n❌ {name} crashed unexpectedly with exit code {ret}")
                    shutdown_all_services(processes)
                    sys.exit(ret)
            time.sleep(2)  # Check interval rhythm

    # Catch Ctrl+C exits smoothly
    except KeyboardInterrupt:
        shutdown_all_services(processes)
    # Catch any global infrastructure errors gracefully
    except Exception as e:
        print(f"\n❌ Script error encountered: {e}")
        shutdown_all_services(processes)

if __name__ == "__main__":
    main()
