#!/usr/bin/env bash
# Make a git worktree run like the live checkout, without touching live data.
#
# A new worktree has the code but none of the gitignored pieces the app needs,
# so its tests fail on missing data and every session improvises. This gives
# each worktree the same setup:
#
#   api/.venv                          link to the live one (run, never written)
#   api/data                           copy-on-write clone (APFS): real data to
#                                      test against; any write stays in the clone
#   api/backtest/hypothesis_log.jsonl  clone, likewise
#   web/node_modules                   clone (Turbopack refuses a link that
#                                      leaves the project root)
#
# Left out on purpose: api/.env and the Kite session files, so a worktree never
# holds the secrets or acts as the logged-in account. --with-kite clones the
# Kite session too, for a preview that needs live Kite data.
#
# Usage, from inside the worktree or with its path:
#   scripts/worktree_env.sh [worktree_dir] [--with-kite]
# Re-running is safe: what is already there is left alone. Before
# `git worktree remove`, delete the api/.venv link first; the rest are clones.

set -euo pipefail

WITH_KITE=false
DIR=""
for a in "$@"; do
    case "$a" in
        --with-kite) WITH_KITE=true ;;
        -*) echo "unknown option $a" >&2; exit 2 ;;
        *) DIR="$a" ;;
    esac
done

DIR="$(cd "${DIR:-.}" && git rev-parse --show-toplevel)"
LIVE="$(git -C "$DIR" worktree list --porcelain | awk '/^worktree /{print substr($0, 10); exit}')"
if [[ "$DIR" == "$LIVE" ]]; then
    echo "worktree_env: $DIR is the live checkout, not a worktree — nothing to do." >&2
    exit 1
fi

for p in api/data api/backtest/hypothesis_log.jsonl; do
    if [[ -L "$DIR/$p" ]]; then
        echo "worktree_env: $p is a link, so tests here would write to live data." >&2
        echo "Remove the link (rm $DIR/$p) and run this again to get a clone." >&2
        exit 1
    fi
done

clone() {  # APFS copy-on-write; a plain copy where the disk cannot clone
    local src="$1" dst="$2" name="${2#"$DIR"/}"
    if [[ -e "$dst" ]]; then echo "  have   $name"; return; fi
    if [[ ! -e "$src" ]]; then echo "  skip   $name (the live checkout has none)"; return; fi
    mkdir -p "$(dirname "$dst")"
    cp -cR "$src" "$dst" 2>/dev/null || cp -R "$src" "$dst"
    echo "  clone  $name"
}

echo "worktree: $DIR"
echo "live:     $LIVE"
if [[ -e "$DIR/api/.venv" || -L "$DIR/api/.venv" ]]; then
    echo "  have   api/.venv"
else
    ln -s "$LIVE/api/.venv" "$DIR/api/.venv"
    echo "  link   api/.venv"
fi
clone "$LIVE/api/data" "$DIR/api/data"
if ! $WITH_KITE; then
    rm -f "$DIR"/api/data/kite_*.json
fi
clone "$LIVE/api/backtest/hypothesis_log.jsonl" "$DIR/api/backtest/hypothesis_log.jsonl"
clone "$LIVE/web/node_modules" "$DIR/web/node_modules"
# Next writes its route types (LayoutProps and the like) into .next/types on a
# build or dev run; without them tsc fails in a fresh worktree.
if [[ -d "$DIR/web/.next/types" ]]; then
    echo "  have   web/.next/types"
elif [[ -d "$DIR/web/node_modules" ]] && (cd "$DIR/web" && npx next typegen >/dev/null 2>&1); then
    echo "  types  web/.next/types (next typegen)"
else
    echo "  WARNING: could not generate web/.next/types — tsc will fail until a build or dev run" >&2
fi
