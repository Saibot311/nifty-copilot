# Sourced by land.sh (and scripts/test_land_rollback.sh).
#
# health_after_restart <base> <restart-command> <url>...
#   Every URL must answer 200 within LAND_HEALTH_WAIT seconds (default 60).
#   If one does not, main is reset to <base> (the commit before the landing),
#   <restart-command> brings the old code back up, and it returns 1. Called
#   before the push: a landing that breaks the app never reaches GitHub.
health_after_restart() {
    local base="$1" restart_cmd="$2"
    shift 2
    local wait="${LAND_HEALTH_WAIT:-60}" url ok
    for url in "$@"; do
        ok=false
        for _ in $(seq 1 "$wait"); do
            if [[ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$url")" == "200" ]]; then ok=true; break; fi
            sleep 1
        done
        if ! $ok; then
            echo "health: $url did not answer within ${wait}s — rolling main back to ${base:0:7}"
            git reset -q --hard "$base" || return 2
            eval "$restart_cmd"
            return 1
        fi
    done
    echo "health: every page answers"
    return 0
}
