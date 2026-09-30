# Working in this repo

The live checkout (the repo root, branch `main`) is what the dashboard and the 19:30 IST nightly job
run. Several Claude sessions work here at once, each in its own worktree. These rules keep their work
easy to merge. The project's own ground rules (the evidence ladder, frozen hypotheses, buyer-only
framing, irreplaceable data, paid services) are in `docs/HANDOFF.md` under "Ground rules that must not
slip"; read them before changing research code.

## Develop in a worktree

- Work in your own git worktree on your own branch (`claude/<name>`), never in the live checkout.
- Run `scripts/worktree_env.sh` once in a new worktree. It links the venv, clones `api/data`, the
  hypothesis log and `web/node_modules` copy-on-write, and generates Next's route types, so the full
  test suite, the audit and the web build run there as in main without touching live data. The Kite
  session files and `api/.env` are left out.
- Commit on your branch. Keep edits to shared docs (`docs/ARCHITECTURE.md`, `docs/HANDOFF.md`,
  `docs/DESIGN.md`) to your own rows and paragraphs; rewrapping neighbouring text is what turns
  separate edits into conflicts.
- Before landing, bring the branch up to date in its worktree: `git merge main`, resolve any conflict
  there, and re-run `scripts/check_all.sh --fast`.

## Land with `scripts/land.sh`

- `scripts/land.sh <branch> --dry-run` merges in a scratch worktree and runs every check, the secret
  scan and the hypothesis-log guard, changing nothing.
- `scripts/land.sh <branch>` then fast-forwards main and restarts only what changed. `--push` also
  pushes main. Pass `-m` with the merge message, including the Co-Authored-By line.
- Land, commit to main or push only when the user asks. The repo is public.
- Afterwards remove the worktree's `api/.venv` link, then `git worktree remove` it and
  `git branch -d` the branch.

## Never

- Never copy or `git apply` uncommitted work into the live checkout to make it live. That is what
  stopped main fast-forwarding on 27–29 Sep 2026. Land the branch instead.
- Never change the live checkout from 19:20 IST until the nightly job logs "daily job done" in
  `api/data/daily_job.log` (`land.sh` refuses).
- Never link a worktree's `api/data` or hypothesis log to the live ones (`worktree_env.sh` refuses):
  tests would write to data that cannot be regenerated.
- Never commit `AUDIT_REPORT.md`, `api/.env`, anything under `api/data/`, or the notes under
  `docs/research/`, which stay uncommitted by the owner's choice.
