#!/usr/bin/env bash
# =============================================================================
# run.sh — ClinicalTriage-Env single-command launcher
#
# Usage:
#   ./run.sh                        # Start server only
#   ./run.sh --inference            # Start server + run inference agent
#   HF_TOKEN=hf_xxx ./run.sh --inference
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/env"
SERVER_PORT=7860
SERVER_PID_FILE="$SCRIPT_DIR/.server.pid"

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── parse args ───────────────────────────────────────────────────────────────
RUN_INFERENCE=false
for arg in "$@"; do
  [[ "$arg" == "--inference" ]] && RUN_INFERENCE=true
done

# ── 1. activate venv ─────────────────────────────────────────────────────────
info "Activating virtual environment..."
[[ -f "$VENV/bin/activate" ]] || error "venv not found at $VENV. Create it with: python3 -m venv env"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
info "Python: $(python3 --version)"

# ── 2. install / verify dependencies ─────────────────────────────────────────
info "Installing dependencies (quiet)..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# ── 3. kill any leftover server on the port ──────────────────────────────────
if lsof -ti :"$SERVER_PORT" &>/dev/null; then
  warn "Port $SERVER_PORT in use — killing old process..."
  kill "$(lsof -ti :"$SERVER_PORT")" 2>/dev/null || true
  sleep 1
fi

# ── 4. start server in background ────────────────────────────────────────────
info "Starting ClinicalTriage-Env server on port $SERVER_PORT..."
cd "$SCRIPT_DIR"
python3 server.py > "$SCRIPT_DIR/server.log" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$SERVER_PID_FILE"
info "Server PID: $SERVER_PID  (logs → server.log)"

# ── 5. wait for server to be ready ───────────────────────────────────────────
info "Waiting for server to be ready..."
for i in $(seq 1 20); do
  if curl -sf "http://localhost:$SERVER_PORT/health" &>/dev/null; then
    STATUS=$(curl -s "http://localhost:$SERVER_PORT/health")
    info "Server ready! $STATUS"
    break
  fi
  [[ $i -eq 20 ]] && error "Server did not start in time. Check server.log"
  sleep 0.5
done

# ── 6. quick smoke test ───────────────────────────────────────────────────────
info "Running smoke test..."
RESET_RESP=$(curl -sf -X POST "http://localhost:$SERVER_PORT/reset" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task1_esi_assignment", "seed": 1}')
CASE_ID=$(echo "$RESET_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['observation']['patient']['case_id'])")
info "Smoke test passed — patient: $CASE_ID"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Server running at http://localhost:$SERVER_PORT${NC}"
echo -e "${GREEN}  API docs:   http://localhost:$SERVER_PORT/docs${NC}"
echo -e "${GREEN}  Stop with:  kill \$(cat .server.pid)${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# ── 7. run inference agent (optional) ────────────────────────────────────────
if $RUN_INFERENCE; then
  echo ""
  if [[ -z "$HF_TOKEN" ]]; then
    error "HF_TOKEN is not set. Run: HF_TOKEN=hf_xxxx ./run.sh --inference"
  fi
  info "Running inference agent (all 3 tasks)..."
  echo ""
  python3 "$SCRIPT_DIR/inference.py"
  echo ""
  info "Inference complete."
fi
