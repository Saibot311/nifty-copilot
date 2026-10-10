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
#   ./scripts/install_app_services.sh --snapshots  # (re)install only the option-snapshot recorder
#   ./scripts/install_app_services.sh --keepawake  # (re)install only the market-hours keep-awake
#   ./scripts/install_app_services.sh --kronos     # (re)install only Kronos's live forecast
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
SNAP_LABEL="com.niftycopilot.snapshots"
AWAKE_LABEL="com.niftycopilot.keepawake"
KRONOS_LABEL="com.niftycopilot.kronos"
PATH_LINE="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

status() {
    for label in "$API_LABEL" "$WEB_LABEL" "$WATCH_LABEL" "$SNAP_LABEL" "$AWAKE_LABEL" "$KRONOS_LABEL"; do
        if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
            info=$(launchctl print "$DOMAIN/$label")
            state=$(awk -F'= ' '/state = /{print $2; exit}' <<<"$info")
            runs=$(awk -F'= ' '/runs = /{print $2; exit}' <<<"$info")
            last=$(awk -F'= ' '/last exit code = /{print $2; exit}' <<<"$info")
            echo "$label: installed ($state; runs ${runs:-?}; last exit ${last:-none})"
            # A job that exits 78 never reached its own code: launchd could not
            # set it up. The watchdog did this silently for its whole life.
            [[ "$last" == 78* ]] && echo "  WARNING: launchd could not start $label (EX_CONFIG) — see its log paths"
        else
            echo "$label: not installed"
        fi
    done
    # What the sockets are actually bound to — .env says what they should be,
    # which is not the same thing (and the LAN address can change under it).
    for port in 8000 3000; do
        bound=$(lsof -nP -iTCP:$port -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u | tr '\n' ' ')
        echo "port $port: listening on ${bound:-nothing}"
    done
    lan=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
    paired=$(grep '^DASHBOARD_HOSTS=' "$API_DIR/.env" 2>/dev/null | cut -d= -f2 || true)
    if lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | grep -q '\*:8000'; then
        if [[ -n "$lan" ]]; then
            lan_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$lan:8000/health" || true)
            echo "network: every interface; this Mac is $lan now (http://$lan:8000/health -> ${lan_code:-no answer}); phones paired to ${paired:-nothing}"
            [[ ",$paired," != *",$lan,"* ]] && echo "  WARNING: this Mac's address is not the paired one — re-run with --lan"
        else
            echo "network: every interface, but this Mac has no LAN address right now"
        fi
    else
        echo "network: this Mac only (127.0.0.1)"
    fi
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
    # Python is read when the API starts, so backend edits are not live until
    # it restarts. Say so, as the web build check does.
    pid=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -1 || true)
    if [[ -n "$pid" ]]; then
        started=$(ps -o lstart= -p "$pid" | sed 's/^ *//; s/ *$//')
        newer=$(find "$API_DIR" -name '*.py' -not -path '*/.venv/*' -not -path '*/tests/*' -newermt "$started" 2>/dev/null | head -1)
        if [[ -n "$newer" ]]; then
            echo "STALE: backend code changed since the API started ($started) — re-run this script to load it"
        else
            echo "api: running the code on disk (started $started)"
        fi
    fi
}

# The option-snapshot recorder (api/scripts/snapshot_options.py): NSE's chain
# every five minutes of the session, the only intraday option prices there
# will ever be. It exits at once outside 09:15-15:35 on a weekday.
install_snapshots() {
    launchctl bootout "$DOMAIN/$SNAP_LABEL" 2>/dev/null || true
    mkdir -p "$HOME/Library/LaunchAgents" "$API_DIR/data"
    cat > "$HOME/Library/LaunchAgents/$SNAP_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$SNAP_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$API_DIR/.venv/bin/python</string>
        <string>$API_DIR/scripts/snapshot_options.py</string>
    </array>
    <key>WorkingDirectory</key><string>$API_DIR</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>$PATH_LINE</string></dict>
    <key>StartCalendarInterval</key>
    <array>
$(for m in 0 5 10 15 20 25 30 35 40 45 50 55; do echo "        <dict><key>Minute</key><integer>$m</integer></dict>"; done)
    </array>
    <key>RunAtLoad</key><false/>
    <!-- A log launchd creates and owns (see the watchdog's note). -->
    <key>StandardOutPath</key><string>$API_DIR/data/snapshots.launchd.log</string>
    <key>StandardErrorPath</key><string>$API_DIR/data/snapshots.launchd.log</string>
</dict>
</plist>
PLIST
    launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$SNAP_LABEL.plist"
}

# Keeps this Mac awake through the session, 09:05-15:36 IST on weekdays, so the
# snapshot recorder's runs happen: on 1 Oct 2026 it slept through 09:35-09:55
# and 10:10, and a missed run is a price that can never be recorded. It runs
# macOS's own caffeinate (no idle or, on power, system sleep; the display may
# still sleep) and ends at 15:36 by itself. A closed lid still sleeps the Mac.
install_keepawake() {
    launchctl bootout "$DOMAIN/$AWAKE_LABEL" 2>/dev/null || true
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$HOME/Library/LaunchAgents/$AWAKE_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$AWAKE_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>now=\$(date +%s); start=\$(date -j -f %H:%M:%S 09:05:00 +%s); end=\$(date -j -f %H:%M:%S 15:36:00 +%s); [ "\$(date +%u)" -le 5 ] &amp;&amp; [ "\$now" -ge "\$start" ] &amp;&amp; [ "\$now" -lt "\$end" ] &amp;&amp; exec /usr/bin/caffeinate -is -t \$((end - now)); exit 0</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
$(for d in 1 2 3 4 5; do echo "        <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>5</integer></dict>"; done)
    </array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
    launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$AWAKE_LABEL.plist"
}

if [[ "${1:-}" == "--status" ]]; then
    status
    exit 0
fi

# Kronos's live forecast (api/scripts/kronos_live.py): the next hour of NIFTY's
# five-minute candles, every 15 minutes of the session, a minute after the bar
# closes; the same run scores the forecasts whose hour has passed. Outside the
# session it only scores. Kronos itself lives in ~/Documents/kronos.
install_kronos() {
    launchctl bootout "$DOMAIN/$KRONOS_LABEL" 2>/dev/null || true
    mkdir -p "$HOME/Library/LaunchAgents" "$API_DIR/data"
    cat > "$HOME/Library/LaunchAgents/$KRONOS_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$KRONOS_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$API_DIR/.venv/bin/python</string>
        <string>$API_DIR/scripts/kronos_live.py</string>
    </array>
    <key>WorkingDirectory</key><string>$API_DIR</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>$PATH_LINE</string></dict>
    <key>StartCalendarInterval</key>
    <array>
$(for d in 1 2 3 4 5; do for h in 9 10 11 12 13 14 15; do for m in 1 16 31 46; do echo "        <dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$h</integer><key>Minute</key><integer>$m</integer></dict>"; done; done; done)
    </array>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>$API_DIR/data/kronos.launchd.log</string>
    <key>StandardErrorPath</key><string>$API_DIR/data/kronos.launchd.log</string>
</dict>
</plist>
PLIST
    launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$KRONOS_LABEL.plist"
}

if [[ "${1:-}" == "--kronos" ]]; then
    install_kronos
    echo "Installed $KRONOS_LABEL: Kronos's next-hour forecast every 15 minutes of the session"
    exit 0
fi

if [[ "${1:-}" == "--keepawake" ]]; then
    install_keepawake
    echo "Installed $AWAKE_LABEL: the Mac stays awake 09:05-15:36 IST on weekdays"
    exit 0
fi

if [[ "${1:-}" == "--snapshots" ]]; then
    install_snapshots
    echo "Installed $SNAP_LABEL: NSE's option chain every 5 minutes of the session -> api/data/option_snapshots.db"
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
launchctl bootout "$DOMAIN/$SNAP_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/$AWAKE_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/$KRONOS_LABEL" 2>/dev/null || true

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$HOME/Library/LaunchAgents/$API_LABEL.plist" "$HOME/Library/LaunchAgents/$WEB_LABEL.plist" \
          "$HOME/Library/LaunchAgents/$WATCH_LABEL.plist" "$HOME/Library/LaunchAgents/$SNAP_LABEL.plist" \
          "$HOME/Library/LaunchAgents/$AWAKE_LABEL.plist" "$HOME/Library/LaunchAgents/$KRONOS_LABEL.plist"
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
    <!-- launchd's default is 256 open files. A leak (one socket per Yahoo
         fetch, since fixed) ran the API into it; this is the margin. -->
    <key>SoftResourceLimits</key>
    <dict><key>NumberOfFiles</key><integer>4096</integer></dict>
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
    <!-- Not health_watch.log: the script writes that one itself, and a file it
         created from a shell carries no permission for launchd to open, so
         every run failed before Python started (exit 78). launchd makes this
         one, and owns it. -->
    <key>StandardOutPath</key><string>$API_DIR/data/health_watch.launchd.log</string>
    <key>StandardErrorPath</key><string>$API_DIR/data/health_watch.launchd.log</string>
</dict>
</plist>
PLIST

launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$API_LABEL.plist"
launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$WEB_LABEL.plist"
launchctl bootstrap "$DOMAIN" "$HOME/Library/LaunchAgents/$WATCH_LABEL.plist"
install_snapshots
install_keepawake
install_kronos

echo "Installed. Give them a few seconds, then:"
if [[ -n "$LAN_IP" ]]; then
    echo "  dashboard  http://127.0.0.1:3000  (and http://$LAN_IP:3000 with a paired device)"
else
    echo "  dashboard  http://127.0.0.1:3000  (this Mac only — use --lan for your phone)"
fi
echo "  api        http://127.0.0.1:8000"
echo "Logs: $API_DIR/data/api_service.log, web_service.log, health_watch.log (+ health_watch.launchd.log)"
echo "A watchdog checks both every 10 minutes and restarts one that stops answering."
