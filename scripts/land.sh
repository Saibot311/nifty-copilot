#!/usr/bin/env bash
# Land a branch on main: merge it in a scratch worktree, check everything
# there, then fast-forward the live checkout and restart only what changed.
#
# Why this shape: the live checkout's files are what the dashboard and the
# 19:30 IST nightly job run. Work copied into them uncommitted (27-29 Sep 2026)
# left main unable to fast-forward and made every later merge a hand job. So
# the live checkout only ever moves by fast-forwarding to a commit that has
# passed every check, and never while the nightly job runs.
#
# Usage, from anywhere in the repo:
#   scripts/land.sh <branch> [--dry-run] [--push] [-m "message"]
#
#   --dry-run  merge and check in the scratch worktree, report, change nothing
#   --push     push main to origin once landed
#   -m         the merge commit's message (default "Merge <branch>: <its last subject>")
#
# It stops, changing nothing, when:
#   - main has uncommitted edits to tracked files (commit them on a branch);
#   - the nightly job is running, or starts within ten minutes (weekdays 19:20);
#   - the branch conflicts with main (merge main into the branch in its own
#     worktree, resolve and test there, then land again);
#   - any check fails: pytest, tsc, the page's lock, ESLint, and the web build
#     when web/ changed;
#   - the secret scan finds a .env value, a home path, the git email, a Kite
#     user ID or a private IP in the added lines, or the diff adds a file that
#     must never be committed;
#   - the real hypothesis log changed while the checks ran.

set -uo pipefail

BRANCH="" PUSH=false DRY=false MSG=""
while (($#)); do
    case "$1" in
        --push) PUSH=true ;;
        --dry-run) DRY=true ;;
        -m) MSG="${2:-}"; shift ;;
        -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
        -*) echo "land: unknown option $1" >&2; exit 2 ;;
        *) BRANCH="$1" ;;
    esac
    shift
done
[[ -n "$BRANCH" ]] || { sed -n '2,29p' "$0"; exit 2; }

LIVE="$(git worktree list --porcelain | awk '/^worktree /{print substr($0, 10); exit}')"
cd "$LIVE" || exit 1
LOG="$LIVE/api/backtest/hypothesis_log.jsonl"
SCRATCH=""

cleanup() {
    if [[ -n "$SCRATCH" && -d "$SCRATCH" ]]; then
        [[ -L "$SCRATCH/api/.venv" ]] && rm "$SCRATCH/api/.venv"
        git -C "$LIVE" worktree remove --force "$SCRATCH" >/dev/null 2>&1
    fi
    SCRATCH=""
}
trap cleanup EXIT
die() { printf "\033[31mland: %b\033[0m\n" "$*" >&2; cleanup; exit 1; }
step() { printf "\n\033[1m== %s\033[0m\n" "$*"; }
log_sum() { [[ -f "$LOG" ]] && shasum -a 256 "$LOG" | cut -c1-16 || echo none; }

nightly_job_clear() {
    if pgrep -f "scripts/daily_job.py" >/dev/null; then
        die "the nightly job is running — land after it logs 'daily job done' in api/data/daily_job.log"
    fi
    local now dow
    now=$(TZ=Asia/Kolkata date +%H%M)
    dow=$(TZ=Asia/Kolkata date +%u)
    if ((dow <= 5 && 10#$now >= 1920 && 10#$now < 1931)); then
        die "the nightly job starts at 19:30 IST — land after it logs 'daily job done'"
    fi
}

# ---------------------------------------------------------------------------
step "Before anything: main, the branch, the nightly job"
[[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] || die "the live checkout is not on main"
dirty="$(git status --porcelain --untracked-files=no)"
[[ -z "$dirty" ]] || die "main has uncommitted edits to tracked files — commit them on a branch and land that:\n$dirty"
git rev-parse --verify -q "$BRANCH^{commit}" >/dev/null || die "no branch or commit called $BRANCH"
if git merge-base --is-ancestor "$BRANCH" main; then
    echo "land: $BRANCH is already in main — nothing to do"
    trap - EXIT
    exit 0
fi
nightly_job_clear
BASE="$(git rev-parse main)"
echo "main $(git rev-parse --short "$BASE"); $BRANCH $(git rev-parse --short "$BRANCH") ($(git rev-list --count "$BASE..$BRANCH") commits)"

# ---------------------------------------------------------------------------
step "Merge in a scratch worktree"
SCRATCH="$LIVE/.claude/worktrees/land-${BRANCH//\//-}"
if [[ -e "$SCRATCH" ]]; then
    S="$SCRATCH"; SCRATCH=""
    die "$S already exists: another landing is running, or one was left behind (git worktree remove --force it)"
fi
git worktree add -q --detach "$SCRATCH" "$BASE" || die "could not create the scratch worktree"
MSG="${MSG:-Merge $BRANCH: $(git log -1 --format=%s "$BRANCH")}"
if ! git -C "$SCRATCH" merge -q --no-ff -m "$MSG" "$BRANCH"; then
    conflicts="$(git -C "$SCRATCH" diff --name-only --diff-filter=U | tr '\n' ' ')"
    git -C "$SCRATCH" merge --abort
    die "$BRANCH conflicts with main in: $conflicts\nMerge main into $BRANCH in its own worktree, resolve and test there, then land again."
fi
MERGED="$(git -C "$SCRATCH" rev-parse HEAD)"
CHANGED="$(git diff --name-only "$BASE" "$MERGED")"
echo "$(wc -l <<<"$CHANGED" | tr -d ' ') files change"

# ---------------------------------------------------------------------------
step "Check it there, on a clone of the live data"
"$SCRATCH/scripts/worktree_env.sh" "$SCRATCH" >/dev/null || die "could not set up the scratch worktree"
LOG_BEFORE="$(log_sum)"
"$SCRATCH/scripts/check_all.sh" --fast || die "checks failed — nothing was landed"
if grep -q '^web/' <<<"$CHANGED"; then
    (cd "$SCRATCH/web" && npm run build >/dev/null 2>&1) || die "the web build failed — nothing was landed"
    echo "web build: ok"
fi
[[ "$(log_sum)" == "$LOG_BEFORE" ]] || die "the real hypothesis log changed while checking — find the test that wrote to it"

# ---------------------------------------------------------------------------
step "Secret scan of the added lines"
git diff "$BASE" "$MERGED" | ENV_FILE="$LIVE/api/.env" EMAIL="$(git config user.email)" python3 -c '
import os, re, sys
diff = sys.stdin.read()
lines = diff.splitlines()
added = "\n".join(l[1:] for l in lines if l.startswith("+") and not l.startswith("+++"))
files = [l[6:] for l in lines if l.startswith("+++ b/")]
values = []
try:
    for line in open(os.environ["ENV_FILE"]):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            v = line.split("=", 1)[1].strip().strip("\x27\"")
            if len(v) >= 6:
                values.append(v)
except FileNotFoundError:
    pass
email = os.environ.get("EMAIL", "")
home = os.path.expanduser("~")
found = {
    ".env values": sum(v in added for v in values),
    "home path": added.count(home),
    "git email": added.count(email) if email else 0,
    "Kite user ID": len(re.findall(r"\bERF\d{3}\b", added)),
    "private IP": len(re.findall(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b", added)),
    "never-commit files": sum(f == "AUDIT_REPORT.md" or f.endswith(".env") or f.startswith("api/data/") for f in files),
}
print(f"{len(values)} .env values checked; " + ", ".join(f"{k} {v}" for k, v in found.items()))
sys.exit(1 if any(found.values()) else 0)
' || die "the secret scan found something — nothing was landed"

if $DRY; then
    step "Dry run: every check passed; main was not moved"
    exit 0
fi

# ---------------------------------------------------------------------------
step "Fast-forward main"
nightly_job_clear
[[ "$(git rev-parse main)" == "$BASE" ]] || die "main moved while checking — run land.sh again"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "main's files were edited while checking — nothing was landed"
git merge -q --ff-only "$MERGED" || die "the fast-forward failed — main is unchanged"
echo "main is now $(git log --oneline -1)"

# ---------------------------------------------------------------------------
step "Restart what changed"
DOMAIN="gui/$(id -u)"
wait_for() {  # wait_for <url> <what>
    for _ in $(seq 1 60); do
        [[ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$1")" == "200" ]] && { echo "$2: up"; return 0; }
        sleep 1
    done
    echo "WARNING: $2 did not answer at $1 within a minute — check api/data/*_service.log"
}
if grep -E '^api/' <<<"$CHANGED" | grep -qvE '^api/tests/'; then
    launchctl kickstart -k "$DOMAIN/com.niftycopilot.api" && wait_for http://127.0.0.1:8000/health "API"
else
    echo "API: no change"
fi
if grep -E '^web/' <<<"$CHANGED" | grep -qvE '^web/gate\.test\.mjs$'; then
    (cd "$LIVE/web" && npm run build >/dev/null 2>&1) || echo "WARNING: the live web build failed — the dashboard still serves the old build"
    launchctl kickstart -k "$DOMAIN/com.niftycopilot.web" && wait_for http://127.0.0.1:3000/ "dashboard"
else
    echo "dashboard: no change"
fi

if $PUSH; then
    step "Push"
    git push origin main || die "landed locally, but the push failed"
fi

step "Landed $BRANCH"
echo "The branch and its worktree can go: remove the worktree's api/.venv link, then"
echo "  git worktree remove <its path> && git branch -d $BRANCH"
