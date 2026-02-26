"""
run_coverage.py
===============
Single script that:
  1. Sets SECRET_KEY so tests don't crash at import time
  2. Runs Auth Service tests  → produces htmlcov/auth/index.html
  3. Runs Organization Service tests → produces htmlcov/organization/index.html
  4. Opens both HTML reports in your browser automatically

Usage (from emp_r&r/ root):
    python run_coverage.py

Requirements:
    pip install pytest pytest-cov pytest-asyncio
"""

import os
import sys
import subprocess
import webbrowser
from pathlib import Path

# ── 0. Set env variables before anything else ────────────────────────────────
os.environ.setdefault("SECRET_KEY",    "test-secret-key-minimum-32-characters-long!!")
os.environ.setdefault("DATABASE_URL",  "postgresql://test:test@localhost:5432/test_db")
os.environ.setdefault("SMTP_HOST",     "smtp.gmail.com")
os.environ.setdefault("SMTP_PORT",     "587")
os.environ.setdefault("SMTP_USERNAME", "test@example.com")
os.environ.setdefault("SMTP_PASSWORD", "test-password")
os.environ.setdefault("FRONTEND_URL",  "http://localhost:3000")

ROOT = Path(__file__).parent


def banner(text: str) -> None:
    line = "=" * 60
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}\n")


def run_coverage(service: str, test_dir: str, cfg_file: str, html_dir: str, xml_file: str) -> int:
    """Run pytest with coverage for one service. Returns exit code."""
    banner(f"Running: {service}")

    cmd = [
        sys.executable, "-m", "pytest",
        test_dir,
        f"--cov=src/{service}",
        f"--cov-config={cfg_file}",
        "--cov-report=term-missing",
        f"--cov-report=html:{html_dir}",
        f"--cov-report=xml:{xml_file}",
        "--cov-fail-under=80",
        "-v",
        "--tb=short",
        "--import-mode=importlib",
    ]

    print(f"Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def open_report(html_path: Path) -> None:
    """Open an HTML file in the default browser."""
    if html_path.exists():
        print(f"\n📊 Opening report: {html_path}")
        webbrowser.open(html_path.as_uri())
    else:
        print(f"\n⚠️  Report not found: {html_path} — check for test errors above")


def main() -> None:
    print("\n🚀 EMP R&R — Coverage Runner")
    print("    Runs Auth + Organization services and opens both HTML reports\n")

    exit_codes = []

    # ── Auth Service ──────────────────────────────────────────────────────────
    code_auth = run_coverage(
        service  = "auth",
        test_dir = "src/auth/tests",
        cfg_file = "setup.auth.cfg",
        html_dir = "htmlcov/auth",
        xml_file = "coverage-auth.xml",
    )
    exit_codes.append(("Auth Service", code_auth))

    # ── Organization Service ──────────────────────────────────────────────────
    code_org = run_coverage(
        service  = "organization",
        test_dir = "src/organization/tests",
        cfg_file = "setup.organization.cfg",
        html_dir = "htmlcov/organization",
        xml_file = "coverage-organization.xml",
    )
    exit_codes.append(("Organization Service", code_org))

    # ── Open both HTML reports ────────────────────────────────────────────────
    banner("Opening HTML Reports")
    open_report(ROOT / "htmlcov" / "auth"         / "index.html")
    open_report(ROOT / "htmlcov" / "organization"  / "index.html")

    # ── Final summary ─────────────────────────────────────────────────────────
    banner("Summary")
    all_passed = True
    for service_name, code in exit_codes:
        status = "✅ PASSED" if code == 0 else "❌ FAILED"
        print(f"  {status}  —  {service_name}  (exit code: {code})")
        if code != 0:
            all_passed = False

    print()
    if all_passed:
        print("✅ All services passed coverage threshold (≥ 80%)")
        print()
        print("   Auth report:  htmlcov/auth/index.html")
        print("   Org report:   htmlcov/organization/index.html")
    else:
        print("❌ One or more services failed. Check output above.")

    print()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()