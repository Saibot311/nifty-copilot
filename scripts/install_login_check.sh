#!/usr/bin/env bash
# Installs (or removes) the macOS LaunchAgent that checks the Zerodha session
# on weekday mornings and, if today has none, opens the login page and raises
# a notification. Password and 2FA happen on Zerodha's own site: nothing here
# stores or replays a credential, which is why a person still has to tap.
#
# Runs at 08:45 (before the 9:15 open) and again at 12:30 if you missed it.
#
#   ./scripts/install_login_check.sh            # install / update
#   ./scripts/install_login_check.sh --remove   # uninstall

set -euo pipefail

LABEL="com.niftycopilot.logincheck"
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

times=""
for weekday in 1 2 3 4 5; do
    for hm in "8 45" "12 30"; do
        set -- $hm
        times+="
        <dict><key>Weekday</key><integer>$weekday</integer><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"
    done
done

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$API_DIR/.venv/bin/python</string>
        <string>$API_DIR/scripts/kite_login.py</string>
    </array>
    <key>WorkingDirectory</key><string>$API_DIR</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
    <key>StartCalendarInterval</key>
    <array>$times
    </array>
    <key>StandardOutPath</key><string>$API_DIR/data/login_check.log</string>
    <key>StandardErrorPath</key><string>$API_DIR/data/login_check.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed $LABEL — weekdays 08:45 and 12:30. Log: $API_DIR/data/login_check.log"
echo "It opens Zerodha's login page when today has no session. You complete it; nothing is stored."
