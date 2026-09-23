#!/usr/bin/env bash
# Phase 15 — deployment, on this Mac.
#
# Installs two LaunchAgents so the dashboard is simply *there*: the API and
# the web app start at login, restart if they crash, and need no session and
# nobody to run a command. Both bind to 127.0.0.1 only — this holds a broker
# session and a personal journal, and it is not going on a network.
#
#   ./scripts/install_app_services.sh            # build and install, this Mac only
#   ./scripts/install_app_services.sh --lan      # also reachable from your phone, token required
#   ./scripts/install_app_services.sh --remove   # uninstall
#   ./scripts/install_app_services.sh --status   # what is running
#
# --lan binds both services to every interface, so anything on the same
# network can *reach* them. What stops it getting in is the token in
# api/.env: the API admits this Mac without one and demands it from everyone
# else (api/access.py). Pair a phone from the dashboard on the Mac — the QR
# code is the only place the token is shown.
#
# The dev servers use the same ports, so run --remove (or `launchctl bootout`)
# before starting them from a session, and reinstall afterwards.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/api"
WEB_DIR="$ROOT_DIR/web"
DOMAIN="gui/$(id -u)"
API_LABEL="com.niftycopilot.api"
WEB_LABEL="com.niftycopilot.web"
WATCH_LABEL="com.niftycopilot.watchdog"
PATH_LINE="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

status() {
    for label in "$API_LABEL" "$WEB_LABEL" "$WATCH_LABEL"; do
        if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
            state=$(launchctl print "$DOMAIN/$label" | awk -F'= ' '/state = /{print $2; exit}')
            echo "$label: installed ($state)"
        else
            echo "$label: not installed"
        fi
    done
    grep -q '^DASHBOARD_HOSTS=' "$API_DIR/.env" 2>/dev/null \
        && echo "network: reachable from $(grep '^DASHBOARD_HOSTS=' "$API_DIR/.env" | cut -d= -f2) (token required)" \
        || echo "network: this Mac only"
    for url in "http://127.0.0.1:8000/health" "http://127.0.0.1:3000"; do
        # curl prints 000 itself on failure; a second "|| echo 000" made it
        # read "000000". The first hit after a restart can take ~15s.
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$url" || true)
        echo "$url -> ${code:-no answer}"
    done
    # The service serves a build, not the working tree: code edited since
    # that build is not live until this script is run again.
    if [[ -d "$WEB_DIR/.next" ]]; then
        newest=$(find "$WEB_DIR/src" -type f -newer "$WEB_DIR/.next" 2>/dev/null | head -1)
        if [[ -n "$newest" ]]; then
            echo "STALE: web sources changed since the last build — re-run this script to deploy them"
        else
            echo "build: up to date with web/src"
        fi
    fi
    echo "api: restarts on its own; python is read at start, so re-run this script after backend changes too"
}

if [[ "${1:-}" == "--status" ]]; then
    status
    exit 0
fi

BIND="127.0.0.1"
LAN_IP=""
if [[ "${1:-}" == "--lan" ]]; then
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
    if [[ -z "$LAN_IP" ]]; then
        echo "No Wi-Fi/Ethernet address found — connect to a network first." >&2
        exit 1
    fi
    # The token is what does the protecting; refuse to expose anything without one.
    "$API_DIR/.venv/bin/python" -c "import sys; sys.path.insert(0, '$API_DIR'); import access; access.ensure_token()"
    python3 - "$API_DIR/.env" "$LAN_IP" <<'PYEOF'
import sys, pathlib
env, ip = pathlib.Path(sys.argv[1]), sys.argv[2]
lines = [ln for ln in env.read_text().splitlines() if not ln.startswith("DASHBOARD_HOSTS=")]
lines.append(f"DASHBOARD_HOSTS={ip}")
env.write_text("\n".join(lines) + "\n")
env.chmod(0o600)
PYEOF
    BIND="0.0.0.0"
    echo "Reachable on your network at http://$LAN_IP:3000 — pair a phone from the dashboard on this Mac."
fi

launchctl bootout "$DOMAIN/$API_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/$WEB_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/$WATCH_LABEL" 2>/dev/null || true

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$HOME/Library/LaunchAgents/$API_LABEL.plist" "$HOME/Library/LaunchAgents/$WEB_LABEL.plist" \
          "$HOME/Library/LaunchAgents/$WATCH_LABEL.plist"
    echo "Removed $API_LABEL and $WEB_LABEL. The ports are free for dev servers again."
    exit 0
fi

echo "Building the dashboard (next build)…"
(cd "$WEB_DIR" && PATH="$PATH_LINE" npm run build >/dev/null)

write_plist() {
    local label="$1" workdir="$2" logfile="$3"; shift 3
    local args=""
    for a in "$@"; do args+="
        <string>$a</string>"; done
    cat > "$HOME/Library/LaunchAgents/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key>
    <array>$args
    </array>
    <key>WorkingDirectory</key><string>$workdir</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>$PATH_LINE</string><key>NODE_ENV</key><string>production</string></dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$logfile</string>
    <key>StandardErrorPath</key><string>$logfile</string>
</dict>
</plist>
PLIST
}

mkdir -p "$HOME/Library/LaunchAgents" "$API_DIR/data"

# --host 127.0.0.1: this Mac only. One worker, because the caches and the
# SQLite writers live in the process.
write_plist "$API_LABEL" "$API_DIR" "$API_DIR/data/api_service.log" \
    "$API_DIR/.venv/bin/uvicorn" "main:app" "--host" "$BIND" "--port" "8000" "--workers" "1"

write_plist "$WEB_LABEL" "$WEB_DIR" "$API_DIR/data/web_service.log" \
    "/opt/homebrew/bin/npm" "run" "start" "--" "--hostname" "$BIND" "--port" "3000"

# KeepAlive restarts a process that dies. The watchdog covers the other case:
# one that is still running and no longer answering.
cat > "$HOME/Library/LaunchAgents/$WATCH_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$WATCH_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$API_DIR/.venv/bin/python</string>
        <string>$API_DIR/scripts/health_watch.py</string>
    </array>
    <key>WorkingDirectory</key><string>$API_DIR</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>$PATH_LINE</string></dict>
    <key>StartInterval</key><integer>600</integer>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>$API_DIR/data/health_watch.log</string>
    <key>StandardErrorPath</key><string>$API_DIR/data/health_watch.log</string>
</dict>
</plist>
PLIST

launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$API_LABEL.plist"
launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$WEB_LABEL.plist"
launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$WATCH_LABEL.plist"

echo "Installed. Give them a few seconds, then:"
if [[ -n "$LAN_IP" ]]; then
    echo "  dashboard  http://127.0.0.1:3000  (and http://$LAN_IP:3000 with a paired device)"
else
    echo "  dashboard  http://127.0.0.1:3000  (this Mac only — use --lan for your phone)"
fi
echo "  api        http://127.0.0.1:8000"
echo "Logs: $API_DIR/data/api_service.log, web_service.log, health_watch.log"
echo "A watchdog checks both every 10 minutes and restarts one that stops answering."
