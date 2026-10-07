#!/bin/bash
# The rollback land.sh runs when the app does not come back after a landing:
# main returns to its pre-land commit and nothing is pushed. In a throwaway
# repository, against a URL nothing answers.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'cd /; rm -rf -- "$tmp"' EXIT
cd "$tmp" || exit 1
git init -q -b main . && git config user.email t@t && git config user.name t
echo a > f && git add f && git commit -qm A && base="$(git rev-parse HEAD)"
echo b > f && git commit -qam B && landed="$(git rev-parse HEAD)"
source "$here/land_health.sh"
LAND_HEALTH_WAIT=2 health_after_restart "$base" true "http://127.0.0.1:9/health"
rc=$?
[[ $rc -ne 0 ]] || { echo "FAIL: a dead app was reported healthy"; exit 1; }
[[ "$(git rev-parse HEAD)" == "$base" ]] || { echo "FAIL: main was not rolled back"; exit 1; }
[[ "$landed" != "$base" ]] || exit 1
LAND_HEALTH_WAIT=2 health_after_restart "$base" true || { echo "FAIL: no URLs should pass"; exit 1; }
echo "PASS: rolled back to the pre-land commit, nothing pushed"
