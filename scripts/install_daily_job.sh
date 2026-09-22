#!/usr/bin/env bash
# Installs (or removes) the macOS LaunchAgent that runs api/scripts/daily_job.py
# at 19:30 local time, Monday-Friday. If the Mac is asleep then, launchd runs
# it on wake.
#
#   ./scripts/install_daily_job.sh            # install / update
#   ./scripts/install_daily_job.sh --remove   # uninstall

set -euo pipefail

LABEL="com.niftycopilot.dailyjob"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/api"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$PLIST"
    echo "Removed $LABEL"
    exit 0
fi

days=""
for weekday in 1 2 3 4 5; do
    days+="
        <dict><key>Weekday</key><integer>$weekday</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>30</integer></dict>"
done

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$API_DIR/.venv/bin/python</string>
        <string>$API_DIR/scripts/daily_job.py</string>
    </array>
    <key>WorkingDirectory</key><string>$API_DIR</string>
    <!-- launchd starts with a bare PATH: without node the nightly audit
         cannot run the production build, and reports a failure that is only
         a missing toolchain. -->
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
    <key>StartCalendarInterval</key>
    <array>$days
    </array>
    <key>StandardOutPath</key><string>$API_DIR/data/daily_job.launchd.log</string>
    <key>StandardErrorPath</key><string>$API_DIR/data/daily_job.launchd.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $LABEL — runs weekdays at 19:30. Log: $API_DIR/data/daily_job.log"
