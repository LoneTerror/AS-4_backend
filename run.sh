#!/bin/bash

# ============================================================
#  Employee Recognition & Rewards Platform — Service Launcher
#  Starts all available backend microservices in parallel.
# ============================================================

set -e

# Colors for pretty output
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Employee Recognition & Rewards Platform${NC}"
echo -e "${CYAN}  Starting all backend services...${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo ""

# ── Service Definitions ──────────────────────────────────────
# Format:  NAME  MODULE  PORT

declare -a SERVICES=(
  "Auth|src.auth.main:app|8001"
  "Employees|src.employees.main:app|8003"
  "Rewards|src.rewards.main:app|8006"
  "Wallets|src.wallet.main:app|8004"
  "Recognition|src.recognition.main:app|8005"
  "Analytics|src.analytics.main:app|8007"
)

# Array to track background PIDs
PIDS=()

# ── Trap: clean shutdown on Ctrl-C ───────────────────────────
cleanup() {
  echo ""
  echo -e "${YELLOW}⏳ Shutting down all services...${NC}"
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
  done
  wait 2>/dev/null
  echo -e "${GREEN}✅ All services stopped.${NC}"
  exit 0
}

trap cleanup SIGINT SIGTERM

# ── Activate virtual environment if present ──────────────────
if [ -d "$PROJECT_DIR/venv" ]; then
  echo -e "${YELLOW}🐍 Activating virtual environment...${NC}"
  source "$PROJECT_DIR/venv/bin/activate"
fi

# ── Launch each service ──────────────────────────────────────
for entry in "${SERVICES[@]}"; do
  IFS='|' read -r NAME MODULE PORT <<< "$entry"

  echo -e "${GREEN}🚀 Starting ${NAME} service → http://localhost:${PORT}/v1/docs${NC}"
  uvicorn "$MODULE" --host 0.0.0.0 --port "$PORT" --reload &
  PIDS+=($!)
done

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  All services are running!${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}Auth${NC}          → http://localhost:8001/v1/docs"
echo -e "  ${GREEN}Employees${NC}     → http://localhost:8002/v1/docs"
echo -e "  ${GREEN}Rewards${NC}       → http://localhost:8006/v1/docs"
echo -e "  ${GREEN}Wallets${NC}       → http://localhost:8004/v1/docs"
echo -e "  ${GREEN}Recognition${NC}   → http://localhost:8005/v1/docs"
echo -e "  ${GREEN}Analytics${NC}     → http://localhost:8007/v1/docs"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services.${NC}"

# ── Wait for all background processes ────────────────────────
wait
