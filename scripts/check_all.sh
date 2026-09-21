#!/usr/bin/env bash
# Project-wide health check for NIFTY Copilot.
#
# Runs everything that should stay true as the codebase grows: backend
# tests, type/lint checks on both sides, and (if the dev servers are up)
# a smoke test of every API endpoint. Add new checks as new sections —
# each one just needs to set `ok=0` on failure and print what broke.
#
# Usage:
#   ./scripts/check_all.sh          # full check
#   ./scripts/check_all.sh --fast   # skip endpoint smoke test (servers not required)

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/api"
WEB_DIR="$ROOT_DIR/web"
FAST=false
[[ "${1:-}" == "--fast" ]] && FAST=true

PASS=()
FAIL=()

section() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
ok()      { PASS+=("$1"); printf "\033[32mOK\033[0m  %s\n" "$1"; }
bad()     { FAIL+=("$1"); printf "\033[31mFAIL\033[0m %s\n" "$1"; }

# ---------------------------------------------------------------------
section "Backend: Python syntax"
# ---------------------------------------------------------------------
syntax_errors=$(cd "$API_DIR" && python3 -c "
import ast, glob, sys
errors = []
for f in glob.glob('**/*.py', recursive=True):
    if '.venv' in f:
        continue
    try:
        ast.parse(open(f).read(), filename=f)
    except SyntaxError as e:
        errors.append(f'{f}: {e}')
print('\n'.join(errors))
")
if [[ -z "$syntax_errors" ]]; then
    ok "all .py files parse"
else
    bad "python syntax errors"
    echo "$syntax_errors"
fi

# ---------------------------------------------------------------------
section "Backend: pytest (no-lookahead, cost math, metrics, stats, DBs)"
# ---------------------------------------------------------------------
if [[ -f "$API_DIR/.venv/bin/activate" ]]; then
    pytest_out=$(cd "$API_DIR" && source .venv/bin/activate && python -m pytest -q 2>&1)
    pytest_status=$?
    echo "$pytest_out" | tail -15
    if [[ $pytest_status -eq 0 ]]; then
        ok "pytest ($(echo "$pytest_out" | grep -oE '[0-9]+ passed' | tail -1))"
    else
        bad "pytest"
    fi
else
    bad "api/.venv not found — run: python3 -m venv api/.venv && pip install -r api/requirements.txt -r api/requirements-dev.txt"
fi

# ---------------------------------------------------------------------
section "Backend: ruff lint (if installed)"
# ---------------------------------------------------------------------
if [[ -f "$API_DIR/.venv/bin/activate" ]] && (cd "$API_DIR" && source .venv/bin/activate && pip show ruff >/dev/null 2>&1); then
    ruff_out=$(cd "$API_DIR" && source .venv/bin/activate && ruff check . 2>&1)
    if [[ $? -eq 0 ]]; then
        ok "ruff"
    else
        bad "ruff"
        echo "$ruff_out" | tail -40
    fi
else
    echo "skipped (ruff not installed — pip install ruff to enable)"
fi

# ---------------------------------------------------------------------
section "Frontend: TypeScript (tsc --noEmit)"
# ---------------------------------------------------------------------
tsc_out=$(cd "$WEB_DIR" && npx tsc --noEmit 2>&1)
if [[ -z "$tsc_out" ]]; then
    ok "tsc --noEmit"
else
    bad "tsc --noEmit"
    echo "$tsc_out" | tail -60
fi

# ---------------------------------------------------------------------
section "Frontend: ESLint"
# ---------------------------------------------------------------------
eslint_out=$(cd "$WEB_DIR" && npx eslint . 2>&1)
if [[ -z "$eslint_out" ]]; then
    ok "eslint"
else
    bad "eslint"
    echo "$eslint_out" | tail -100
fi

# ---------------------------------------------------------------------
if ! $FAST; then
    section "API: endpoint smoke test (requires servers running)"
    ENDPOINTS=(
        health
        api/snapshot
        api/indicators
        api/candles
        api/research/compare
        api/strategies/playbook
        api/briefing
        api/options/chain
        api/options/archive
        api/live
        api/recommendation
        api/zerodha/status
        api/bars/archive
        api/forward_log
        api/patterns/options
        api/patterns/today
        api/live/patterns
        api/similarity
        api/intraday/research
        api/copilot/status
        api/copilot/record
        "api/candles?provider=archive&timeframe=15m&days=10"
    )
    if curl -s -o /dev/null --max-time 3 http://localhost:8000/health; then
        for ep in "${ENDPOINTS[@]}"; do
            # Generous timeout: on a cold cache (fresh server, or after a
            # --reload), /api/recommendation and /api/research/compare
            # re-run all 26 strategies over ~19 years and take tens of
            # seconds. A short timeout reports that as a failure.
            code=$(curl -s -o /tmp/check_all_resp -w "%{http_code}" --max-time 120 "http://localhost:8000/$ep")
            if [[ "$code" == "200" ]]; then
                ok "GET /$ep"
            else
                bad "GET /$ep -> $code"
                head -c 300 /tmp/check_all_resp; echo
            fi
        done
        rm -f /tmp/check_all_resp
    else
        echo "skipped (API server not reachable at :8000 — start it or pass --fast)"
    fi
fi

# ---------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------
printf "\033[32m%d passed\033[0m, \033[31m%d failed\033[0m\n" "${#PASS[@]}" "${#FAIL[@]}"
if [[ ${#FAIL[@]} -gt 0 ]]; then
    printf "\nFailed:\n"
    for f in "${FAIL[@]}"; do echo "  - $f"; done
    exit 1
fi
exit 0
