# Sentinel Phase 1 (on the Mac) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the failures in the spec's catalogue on the Mac, repair the safe ones, record every incident append-only, tell the owner (ntfy when configured, macOS notification always), and roll back a landing that breaks the app.

**Architecture:** A new `api/sentinel/` package (checks registry, repairs, incident lifecycle, alerts) run in "fast" mode by the existing 10-minute watchdog and in "deep" mode by the nightly job after the audit. Incidents live in `api/data/incidents.db` (append-only, backed up). `/api/sentinel` serves the state; the freshness strip shows one health line. `land.sh` checks health after its restart and resets main before any push when it fails.

**Tech Stack:** Python 3.13 (stdlib `sqlite3`, `urllib`, `subprocess`), pytest, Next.js 16 / TypeScript, bash.

**Spec:** `docs/superpowers/specs/2026-10-06-sentinel-design.md`

## Global Constraints

- Repairs run at most once per action per 2 hours (`REPAIR_GAP = timedelta(hours=2)`), never between 19:20 and the day's "daily job done" line in `api/data/daily_job.log`.
- No repair ever restores, edits or deletes an irreplaceable database (`forward_log.db`, `journal.db`, `paper.db`, `news.db`, `gift_nifty.db`, `backtest/hypothesis_log.jsonl`, and every DB in `storage/backup.py`). D2 and B2 only alert.
- Restarts of the API or web during market hours (09:15-15:30 IST on a session day) happen only for P1/P2 (not answering); P3 (memory) waits for the close.
- Alerts: one message on open, one on resolve, a reminder after 6 h open, a digest once a day at or after 08:30. Plain text, no secrets, only figures from the finding's evidence.
- ntfy topic from `NTFY_TOPIC` in `api/.env` (server `https://ntfy.sh` unless `NTFY_SERVER` is set). Unset = macOS notification only. The topic is never committed or logged.
- An incident closes after its check passes on 2 consecutive runs.
- Tests never touch live `api/data`: every store takes a `db_path`; every check takes its inputs as arguments or fakes.
- Copy follows DESIGN.md §6: plain English, never advice.

## Review Focus

1. **A check that raises** (bug, missing file, network) must become a finding "check broken: <error>", never stop the other checks or the watchdog → test in Task 3.
2. **The same failure seen every 10 minutes** must not send a message every 10 minutes → test in Task 2 (one open message, one reminder after 6 h).
3. **Flapping** (fail, pass, fail) must not open and close an incident each time → test in Task 3 (closes only after 2 passes; a fail before then keeps it open).
4. **A repair during the nightly job or market hours** must be refused with a reason recorded on the incident → test in Task 3.
5. **The rollback on a broken landing** must leave main at its pre-land commit and must never have pushed → test in Task 7 (dry exercise of the shell function with a fake health URL).

---

### Task 1: Incident store, and the backup list completed

**Files:**
- Create: `api/storage/incidents_db.py`
- Modify: `api/storage/backup.py` (add `backup_breakouts`, `backup_incidents`), `api/scripts/daily_job.py:187-192` (`step_backup` calls both)
- Test: `api/tests/test_incidents_db.py`, `api/tests/test_backup.py` (append)

**Interfaces:**
- Produces:
  - `DB_PATH = api/data/incidents.db`. Tables:
    - `incidents(id INTEGER PK, check_key TEXT, area TEXT, severity TEXT, opened_at TEXT, summary TEXT)`;
    - `events(id INTEGER PK, incident_id INT, at TEXT, kind TEXT, detail TEXT)`, where `kind` ∈ seen, repair, alert, resolved.
  - `open_incident(check_key, area, severity, summary, at, db_path=None) -> int`
  - `add_event(incident_id, kind, detail, at, db_path=None) -> None`
  - `open_incidents(db_path=None) -> list[dict]` returns incidents with no `resolved` event, each with `last_seen`, `seen_count`, `repairs: list[dict]` and `last_alert_at`.
  - `recent(days=14, db_path=None) -> list[dict]`.
  - Insert-only: there is no update or delete function.
  - `backup_breakouts()` uses `_backup(..., "breakouts", "events", ...)`; `backup_incidents()` uses `_backup(..., "incidents", "incidents", ...)`.

- [ ] **Step 1:** Write `test_an_incident_is_written_once_and_only_appended_to` (open, add 2 `seen` and 1 `repair`; `open_incidents` shows `seen_count == 2`, `repairs` has 1; the module exposes no `update`/`delete` names) and `test_a_resolved_incident_is_no_longer_open`. Append `test_breakouts_and_incidents_are_backed_up` to `test_backup.py` (tmp source DBs → verified copies).
- [ ] **Step 2:** Run `cd api && .venv/bin/python -m pytest tests/test_incidents_db.py tests/test_backup.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement the store following `storage/breakout_db.py`'s connect/schema pattern. Add the two backup functions and call them in `step_backup`.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** Commit: "Incidents store, append-only; breakouts and incidents backed up".

### Task 2: Alerts

**Files:**
- Create: `api/sentinel/__init__.py` (empty), `api/sentinel/alerts.py`
- Test: `api/tests/test_sentinel_alerts.py`

**Interfaces:**
- Consumes: `incidents_db.add_event`, `open_incidents`.
- Produces:
  - `send(title: str, body: str, priority: str = "default", post=None, local=None) -> bool`. It POSTs the body to `{NTFY_SERVER}/{NTFY_TOPIC}` with headers `Title` and `Priority`, and always calls the macOS echo. `post` and `local` are injectable for tests.
  - `due(incident: dict, now: datetime) -> str | None` returns "open" when no alert was sent yet, "reminder" when the last alert is ≥ 6 h old and the incident is still open, else None.
  - `digest_due(now, state: dict) -> bool` is true at or after 08:30 IST when `state["digest_on"] != today`.
  - `digest_text(open: list[dict]) -> str`: "All checks passing." or "N open: <summary> (since HH:MM DD Mon); …".

- [ ] **Step 1:** Write the tests:
  - `test_no_topic_means_local_only` (with `NTFY_TOPIC` unset, `post` is never called and `local` is called once);
  - `test_one_open_message_then_a_reminder_after_six_hours` (`due` gives "open", None at +10 min, "reminder" at +6 h);
  - `test_the_digest_runs_once_a_day_after_0830`;
  - `test_the_digest_names_each_open_incident`.
- [ ] **Step 2:** Run `pytest tests/test_sentinel_alerts.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Read env via `access._env`. Send with `urllib.request` and a 10 s timeout; on any network error return False. A failed alert is logged by the caller and never raised. Move the `osascript` call from `health_watch.notify` here as `local_notify(message)`. Make `health_watch.notify`, `daily_job.notify`, `kite_login.notify` and the freshness check's notification call `send(...)`. This covers F3: the 08:45 "log in to Kite" reminder then reaches the phone.
- [ ] **Step 4:** Run the tests plus `tests/test_health_watch*.py` if present. Expected: PASS.
- [ ] **Step 5:** Commit: "Sentinel alerts: ntfy when configured, macOS always, one message per incident".

### Task 3: The engine: checks, repairs, incident lifecycle

**Files:**
- Create: `api/sentinel/core.py`
- Test: `api/tests/test_sentinel_core.py`

**Interfaces:**
- Consumes: Task 1 store, Task 2 `alerts.send`/`due`.
- Produces:
  - `@dataclass(frozen=True) Finding(ok: bool, severity: str = "warn", summary: str = "", evidence: dict = field(default_factory=dict))`, where `severity` ∈ info, warn, critical.
  - `@dataclass(frozen=True) Check(key: str, area: str, modes: tuple[str, ...], detect: Callable[[], Finding], repair: str | None = None, auto: bool = True)`.
  - `REPAIRS: dict[str, Callable[[], tuple[bool, str]]]` is filled by Task 4-6 modules via `register_repair(name, fn)`.
  - `may_repair(name, now, state, in_session: bool, job_running: bool, allow_in_session: bool) -> tuple[bool, str]` returns False with a reason during the job or when the last attempt was < `REPAIR_GAP` ago. In session it is False unless `allow_in_session`.
  - `run(mode: str, checks: list[Check], now: datetime, db_path=None, state_path=None, send=alerts.send, clock=None) -> dict`. For each check of that mode it calls detect inside try/except. An exception becomes `Finding(False, "warn", f"check broken: {e}")`.
    - On a failure: open an incident or record `seen` on the open one, attempt the repair when `auto` and `may_repair`, record a `repair` event (ok, message or refused reason), and send when `due`.
    - On a pass: count consecutive passes in the state file and resolve after 2, with an alert "resolved".
    - Returns `{"checked": n, "failing": [...keys], "opened": [...], "resolved": [...]}`.
  - `STATE_PATH = api/data/sentinel_state.json` stores pass counts, last repair times and `digest_on`.
  - `in_session(now, holidays) -> bool` covers 09:15-15:30 on a session day. `job_running()` reuses `briefing.day_forecast.job_running`.

- [ ] **Step 1:** Write the tests (fake checks, tmp db and state, fake `send` collecting messages):
  - `test_a_failing_check_opens_one_incident_and_one_alert` (two runs, so 1 incident, 2 `seen`, 1 message);
  - `test_a_check_that_raises_is_a_finding_and_the_rest_still_run`;
  - `test_it_resolves_only_after_two_passes` (fail, pass, fail, pass, pass: open throughout, resolved once at the end, 1 resolve message);
  - `test_repairs_are_rate_limited_and_refused_during_the_job_and_session` (refused reasons recorded on the incident);
  - `test_a_repair_that_works_is_recorded`.
- [ ] **Step 2:** Run `pytest tests/test_sentinel_core.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `core.py`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: "Sentinel engine: findings, rate-limited repairs, append-only incidents".

### Task 4: Machine and process checks (P2, P3, P4, D1, D5, M1, M2)

**Files:**
- Create: `api/sentinel/checks_machine.py`
- Test: `api/tests/test_sentinel_machine.py`

**Interfaces:**
- Consumes: `core.Check`, `Finding`, `register_repair`.
- Produces: `machine_checks() -> list[Check]`. Each `detect` is a thin wrapper over a pure function tested directly:
  - **P2:** `slow_api(latencies_s: list[float]) -> Finding` fails when the 95th percentile is > 10. The wrapper does 5 GETs of `http://127.0.0.1:8000/health`. Repair `restart_api` (allowed in session).
  - **P3:** `memory(rss_mb: dict[str, float]) -> Finding` fails when any is > 1536. RSS comes from `ps -axo rss=,command=`, matching `uvicorn main:app` and `next-server`. Repair `restart_api` or `restart_web`, but **not** in session.
  - **P4:** `slow_render(seconds: float) -> Finding` fails when > 8 (a GET of `http://127.0.0.1:3000/`). No repair.
  - **D1:** `disk(free_gb: float) -> Finding` is critical when < 2 and warn when < 5 (`shutil.disk_usage` on `api/data`). Repair `tidy_disk`: gzip `api/data/*.log` over 50 MB to `*.log.1.gz` and truncate them, and delete `api/data/backups` files beyond each stem's keep (reuses `storage.backup` keep rules).
  - **D5:** `clock(skew_s: float) -> Finding` fails when |skew| > 30. Skew is the local UTC time minus the `Date` header of a HEAD request to `https://www.google.com`. No repair; the summary says "the Mac's clock is N s off: System Settings → General → Date & Time → set automatically".
  - **M1:** `sleep_setting(pmset_text: str) -> Finding` fails when the AC `sleep` value is ≠ 0. Its summary carries the exact command `sudo pmset -c sleep 0 disksleep 0 autorestart 1 womp 1`. It is skipped (ok) when not on macOS.
  - **M2:** `power_cut(uptime_min: float, missed_snapshot: bool) -> Finding` fails when uptime is < 15 and a snapshot was missed. Info severity; no repair (the freshness check catches up).
- Fast mode: P2, P3, P4, D1, M2. Deep mode: D5, M1.

- [ ] **Step 1:** Write one test per pure function with the spec's thresholds at the edges, for example `slow_api([0.1]*4+[11])` fails and `disk(4.9)` warns. Add `test_memory_restart_waits_for_the_close` through `core.may_repair` with `allow_in_session=False`, and `test_tidy_disk_never_touches_a_db` on a tmp dir holding `.db` and `.log` files.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. The restart repairs call `health_watch.restart(label)`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: "Sentinel: machine and process checks".

### Task 5: Data and backup checks (D2, D3, D4, B1, B2)

**Files:**
- Create: `api/sentinel/checks_data.py`
- Test: `api/tests/test_sentinel_data.py`

**Interfaces:**
- Produces: `data_checks() -> list[Check]`.
  - **D2:** `integrity(paths: list[Path]) -> Finding` runs `PRAGMA quick_check` opened `?mode=ro`, and fails critical naming each DB not answering `ok`. Deep mode. No repair ("restore needs you").
  - **D3:** `wal_sizes(paths) -> Finding` fails when any `-wal` is > 200 MB. Repair `checkpoint_wal`: `PRAGMA wal_checkpoint(TRUNCATE)`, not in session. Fast mode.
  - **D4:** `gaps(archived: set[date], sessions: list[date]) -> Finding` fails listing the missing sessions. Sessions are the last 30 days from `nse_holidays.is_session`; archived is `bar_archive.index_trading_days` for 1d plus the 5m dates. Repair `fill_bar_gaps`: `backfill_bars.py --timeframe 5m` and `--timeframe 1d`. Deep mode.
  - **B1:** `backups_fresh(stems: dict[str, date | None], today) -> Finding` fails when any irreplaceable stem's newest backup is older than 2 days. Repair `run_backup` (the nightly `step_backup`). Fast mode.
  - **B2:** `restore_test(backup_path, live_path, table) -> Finding` copies to a temp dir, runs `quick_check` and counts rows. It fails when the check is not ok or the backup holds more rows than live (a backup can trail live, never lead). It runs in deep mode only on the 1st of the month or when the last pass was over 30 days ago (`state["restore_tested_on"]`).
  - `IRREPLACEABLE` is a tuple of (stem, live path, table) built from `storage/backup.py`'s functions, which is the single list B1, B2 and D2 read.

- [ ] **Step 1:** Write the tests on tmp DBs:
  - `test_a_corrupt_copy_is_named` (write garbage bytes into a copy);
  - `test_a_large_wal_is_checkpointed_outside_the_session`;
  - `test_missing_sessions_are_listed`;
  - `test_a_stale_backup_is_found`;
  - `test_the_restore_test_opens_the_backup_and_counts_rows`.
- [ ] **Step 2-4:** Fail, implement, pass, as in the earlier tasks.
- [ ] **Step 5:** Commit: "Sentinel: data and backup checks".

### Task 6: Feeds, jobs, time and security checks (F1, F2, F4, J1, J2, J3, T1, T2, T3, S1, S2, S3)

**Files:**
- Create: `api/sentinel/checks_feeds.py`
- Test: `api/tests/test_sentinel_feeds.py`

**Interfaces:**
- Produces: `feed_checks() -> list[Check]`.
  - **F1:** `snapshots_failing(log_tail: list[str], in_session: bool) -> Finding` fails when the last 3 run lines in `snapshots.launchd.log` contain "FAILED" during the session. Fast mode. No repair.
  - **F2:** `chain_shape(payload: dict) -> Finding` requires `records.underlyingValue`, `records.expiryDates` and, for ≥ 1 row, `CE`/`PE` with `lastPrice`, `openInterest`, `impliedVolatility`, `buyPrice1` and `sellPrice1`. It is critical with "NSE's option-chain format changed: missing …". Also `quote_shape(q: dict)` for `live_index_quote` keys `last`, `open`, `high`, `low`, `market_time`. Deep mode, live fetch.
  - **F4:** `hosts_down(results: dict[str, bool], history: dict[str, int]) -> Finding` fails when a host has been down on 2 consecutive deep runs. The hosts are `query1.finance.yahoo.com`, `api.gdeltproject.org` and `www.nseindia.com` (one HEAD each, 10 s).
  - **J1:** `job_missed(log_tail: str, last_session: date, now) -> Finding` fails at or after 08:00 when there is no "daily job done" line dated after that session's 19:30. Repair `catch_up_job`: start `scripts/daily_job.py` detached, at most once a day, refused when `job_running()`. Fast mode.
  - **J2:** `job_overrun(started_at: datetime | None, now) -> Finding` fails when the job is running and started over 4 h ago. The summary names the last step line. Fast mode.
  - **J3:** `job_twice(pids: list[int]) -> Finding` fails when more than one `daily_job.py` process is running (from `ps`). No repair.
  - **T1:** `holidays_known(known_through: date, today) -> Finding` fails when the holiday list does not reach today + 60 days. Deep mode.
  - **T2:** `lot_size(chain_lot: int, configured: int) -> Finding` fails critical when they differ. Deep mode.
  - **T3:** `rate_card_age(rates_as_of: str, today) -> Finding` fails when over 180 days old. Deep mode.
  - **S1/S3:** `audit_security(results: list[dict]) -> Finding` fails when audit rows 1.1, 15.1 or 15.2 have status FAIL in `api/data/audit_results.json`. Deep mode, run after the audit.
  - **S2:** `npm_audit(report: dict) -> Finding` fails on any high or critical advisory from `npm audit --omit=dev --json` in `web/`. Deep mode, only on Sundays.

- [ ] **Step 1:** Write one test per pure function at the spec's edges, plus `test_a_changed_chain_names_the_missing_field` and `test_the_catch_up_runs_once_a_day_and_never_twice`.
- [ ] **Step 2-4:** Fail, implement, pass.
- [ ] **Step 5:** Commit: "Sentinel: feed, job, time and security checks".

### Task 7: Wiring: watchdog, nightly job, API, digest; and the rollback in land.sh

**Files:**
- Create: `api/scripts/sentinel_run.py` (`--mode fast|deep`)
- Modify:
  - `api/scripts/health_watch.py` (after the freshness Popen, Popen `sentinel_run.py --mode fast`);
  - `api/scripts/daily_job.py` (a step "sentinel deep check" after "audit", not in `RETRY_AT_END`);
  - `api/main.py` (`GET /api/sentinel`);
  - `scripts/land.sh`.
- Test: `api/tests/test_sentinel_wiring.py`, `scripts/test_land_rollback.sh`

**Interfaces:**
- Produces:
  - `/api/sentinel` returns `{"checked_at", "open": open_incidents(), "recent": recent(14), "ntfy": bool}`. The topic itself is never returned.
  - `sentinel_run.main(mode)` runs `core.run` with `machine_checks() + data_checks() + feed_checks()` filtered by mode, then the digest when `digest_due`, and writes `api/data/sentinel.json` with the last result.
  - land.sh `health_after_restart()` GETs `/health`, `/api/freshness`, `/api/indicators`, `/api/breakouts` and `/` (web) and requires all 200 within 60 s. On failure, before the push step, it runs `git reset -q --hard "$BASE"`, restarts the same services, sends a local alert via `api/.venv/bin/python -c "from sentinel.alerts import send; …"`, and calls `die "rolled back: <url> failed"`.

- [ ] **Step 1:** Write the tests:
  - `test_the_api_serves_incidents_without_the_topic` (with `NTFY_TOPIC` set in env, the response holds no topic string);
  - `test_the_job_runs_the_deep_check_after_the_audit` (step order in `daily_job`);
  - `test_the_watchdog_starts_the_fast_check`.
  - Also `scripts/test_land_rollback.sh`: in a throwaway clone with a fake `wait_for` URL that returns 500, `health_after_restart` resets HEAD to BASE and exits non-zero without pushing (`git log origin/main` unchanged).
- [ ] **Step 2:** Run `pytest tests/test_sentinel_wiring.py -q && bash scripts/test_land_rollback.sh`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS. Then `scripts/check_all.sh --fast`, which must pass.
- [ ] **Step 5:** Commit: "Sentinel wired in: watchdog every 10 minutes, nightly deep check, /api/sentinel, rollback on a broken landing".

### Task 8: The health line on the dashboard, docs, and live verification

**Files:**
- Modify:
  - `web/src/lib/api.ts` (`Sentinel` type, `fetchSentinel`);
  - `web/src/components/FreshnessStrip.tsx` (adds the health line and the expandable incident list);
  - `web/src/app/page.tsx` (fetch and pass it);
  - `api/briefing/freshness.py` (`Source("sentinel", "System health", "/api/sentinel", "self", ...)`);
  - `docs/HANDOFF.md` (an own paragraph);
  - `docs/DESIGN.md` (the FreshnessStrip row);
  - `docs/ARCHITECTURE.md` (a sentinel row).

**Interfaces:**
- Consumes: `/api/sentinel` from Task 7.
- Produces:
  - The health line: "All checks passing · last check HH:MM", or "N open · <oldest summary> since HH:MM".
  - A button expands the list, showing each incident's summary, when it opened, the repairs tried with their result, and whether it is resolved.
  - Amber for warn, rose only for critical. The word carries the meaning (DESIGN §7).

- [ ] **Step 1:** Run `npx tsc --noEmit` and `npx eslint` on the changed files. Expected: clean.
- [ ] **Step 2:** Run `scripts/check_all.sh --fast`, then `scripts/land.sh claude/sentinel --dry-run`. Expected: all pass.
- [ ] **Step 3:** Outside 19:20 to "daily job done", run `scripts/land.sh claude/sentinel --push -m "…Co-Authored-By…"`.
- [ ] **Step 4:** Verify live:
  - `api/.venv/bin/python api/scripts/sentinel_run.py --mode fast` and `--mode deep` print their results;
  - `/api/sentinel` answers;
  - the line shows on the dashboard at desktop and 375 px;
  - M1 opens an incident (sleep is 1 today) with the pmset command in its summary.
- [ ] **Step 5:** Save a memory note pointing to `api/sentinel/`, then remove the worktree.
