# Sentinel: failure detection, repair, alerts and remote access

Date: 2026-10-06 · Status: draft for the owner's review · Path chosen: **Mac + Oracle watchdog**

## 1. What the owner asked for, and what that means here

> "Create a system of bug recognition and repair; assume broadly what could go wrong and take
> preventive measures; ready to run undisturbed on a server I can reach from anywhere; and the best
> free hosting."

Understood as:

- **Undisturbed:** the dashboard, the 5-minute recorders and the 19:30 job keep running without a
  person at the Mac, and anything they cannot fix themselves reaches the owner's phone.
- **Recognition and repair:** a catalogue of failure modes, each with an automatic check, a
  repair where a safe one exists, and a record of what happened.
- **Reachable from anywhere:** the dashboard on the phone or any laptop, privately, without
  opening the home network to the internet.
- **Hosting:** the Mac stays the server, because NSE refuses connections from cloud data centres
  and the app needs NSE for the option chain, live quotes, snapshots and nightly reports. A free
  Oracle Cloud VM is the outside watchdog and the offsite backup store; it never calls NSE.

Out of scope: new research, new cards (consolidation until 2026-11-06), any trading or execution path,
any paid service.

## 2. What exists already (kept, extended, not duplicated)

| Exists | Where | Gap it leaves |
|---|---|---|
| Watchdog every 10 min, restarts API/web | `scripts/health_watch.py`, launchd | Alerts are macOS pop-ups; no memory or hang limits |
| Freshness check + named fixes | `briefing/freshness.py`, `scripts/freshness_check.py` | Only data age; nothing on disk, DBs, backups, clock, feeds' shape |
| Nightly retries, catch-up after login | `scripts/daily_job.py`, `forecast_catchup.py` | No run budget; a sleeping Mac stretched 5 Oct's run to 02:41 |
| Audit (54 checks) | `scripts/audit.py` | Results only on the Research tab; nobody is told |
| Backups of irreplaceable DBs | `storage/backup.py` → `api/data/backups` | Same disk as the data; newer DBs (breakouts, method choices) not listed; never restore-tested |
| Landing checks | `scripts/land.sh` | No health check after restart, no rollback |
| Pairing token for non-local access | `access.py` | Fine; reused for remote access |

Facts measured on 2026-10-06: the Mac's `pmset` sleep is 1 minute; every alert is `osascript`;
`api/data` is 1.4 GB; the API uses tens of MB of RAM.

## 3. Architecture

```
            ┌──────────────── Mac (the server, home connection) ────────────────┐
 phone ─────┤ Tailscale ── web :3000 ── API :8000 ── data (SQLite)               │
 (anywhere) │                                                                    │
            │ watchdog (10 min) ── sentinel.run(fast) ──┐                         │
            │ nightly job ──────── sentinel.run(deep) ──┼─► incidents.db ──► alerts ──► ntfy ──► phone
            │ land.sh ── post-restart health ── rollback│                         │
            │ backup ──► rsync over Tailscale ──────────┼──────────┐             │
            └───────────────────────────────────────────┼──────────┼─────────────┘
                                                        │ heartbeat│ backups
            ┌──────── Oracle Always Free VM (outside) ──▼──────────▼─────────────┐
            │ probe Mac every 5 min ─► alert if down 3 times or heartbeat late    │
            │ keeps 30 days of backups, verifies they open                         │
            └──────────────────────────────────────────────────────────────────────┘
```

### 3.1 `api/sentinel/` (new package)

- `checks.py`: a registry of `Check(key, area, cadence, detect, repair, auto, severity)`.
  `detect()` returns `Finding(ok, severity, summary, evidence)`; it never raises (an exception
  in a check is itself a finding, "check broken").
- `repairs.py`: named, idempotent repair actions. Each is rate-limited (the freshness check's
  `may_fix` rule, generalised): at most one attempt per action per 2 hours, and never during
  19:20 to "daily job done" unless the job asked for it.
- `incidents.py` + `storage/incidents_db.py`: append-only, the same rules as the forward log.
  An incident opens on the first failing finding, is updated on each later run (the count and the
  last evidence), records every repair attempt and its result, and closes when the check passes
  twice in a row. Nothing is edited or deleted.
- `alerts.py`: one place that tells the owner. Channels: ntfy (a private topic name in
  `api/.env`, never committed), with the macOS notification kept as a local echo.
  - **What is sent:** one message when an incident opens, one when it resolves, and a reminder
    if it is still open after 6 hours. A daily 08:30 digest says "all well" or lists what is open.
  - **No alert storms:** messages are deduplicated per incident.
  - **What a message holds:** short plain text, with no secrets and no figures that are not in
    the evidence.
- `run.py`: `run(mode)`. "fast" runs from the watchdog every 10 minutes; "deep" runs nightly,
  after the audit.

### 3.2 The failure catalogue (first version)

| # | Area | Failure assumed | Detect | Repair (auto unless marked) |
|---|---|---|---|---|
| P1 | Process | API or web down | Probe the port (exists) | Restart (exists) |
| P2 | Process | API hangs or crawls | p95 response time of 5 probes > 10 s | Restart |
| P3 | Process | Memory leak | RSS > 1.5 GB for 2 runs | Restart outside market hours; in session, alert only |
| P4 | Process | Slow renders (a half-hourly cache rebuilt in a request) | Web render > 8 s | Alert (the fix needs code) |
| F1 | Feeds | NSE refuses or throttles | Last 3 snapshot runs failed | Back off (the session already does); alert after 30 min in session |
| F2 | Feeds | NSE changes a response's shape | Nightly canary: required fields present in chain, quote and index report | Alert, "format changed"; never guess |
| F3 | Feeds | Kite login lapsed | Token check (exists, 08:45) | Alert to phone with the login link (reaches the phone over Tailscale) |
| F4 | Feeds | Yahoo, GDELT or DNS down | Reachability of each host | Retry at the job's end (exists); alert if a needed source is down 2 nights running |
| D1 | Data | Disk filling | Free space < 5 GB, or < 2 GB | Rotate logs and drop old cache files; at < 2 GB, alert |
| D2 | Data | SQLite corruption | `PRAGMA quick_check` nightly on every DB | Alert, ask to restore (never auto-restores irreplaceable data) |
| D3 | Data | WAL file grows unbounded | WAL > 200 MB | `PRAGMA wal_checkpoint(TRUNCATE)` outside market hours |
| D4 | Data | Missing sessions in an archive | Gap detector vs NSE's trading calendar | Run the matching backfill `--fill-gaps` |
| D5 | Data | Clock drift | Mac time vs an HTTPS Date header, more than 30 s off | Alert (fixing the clock is a system setting, the owner's) |
| J1 | Jobs | Nightly job missed (Mac asleep or off) | No "daily job done" for the last session by 08:00 | Run the catch-up, then alert |
| J2 | Jobs | Nightly job overruns | Still running after 4 h | Alert with the step it is on |
| J3 | Jobs | Two jobs at once | Lock file held | The second exits (exists in part); alert |
| R1 | Deploys | A landed change breaks the app | After the restart: every page endpoint 200 within 60 s | **Rollback**: reset main to the pre-land commit before it is pushed, restart, alert |
| T1 | Time | Holiday list for the next 60 days missing | Calendar coverage | Alert in December for the next year |
| T2 | Time | Lot size changed by NSE | Chain `lot_size` vs `LOT_SIZE` | Alert (costs and sizing depend on it) |
| T3 | Time | Rate card stale | `rates_as_of` older than 180 days | Alert to re-verify STT and charges |
| B1 | Backups | A backup missing or older than 2 days | Directory scan for every irreplaceable DB | Run the backup |
| B2 | Backups | Backups that do not restore | Monthly: open each newest backup in a temp dir, run `quick_check`, and count rows against the live DB | Alert |
| B3 | Backups | Disk dies | Offsite copy on the Oracle VM older than 2 days | Re-run rsync; alert |
| S1 | Security | Dashboard reachable without the token | Audit 15.1 (exists), now alerting | Alert |
| S2 | Security | Vulnerable dependency | Weekly `pip-audit` and `npm audit --omit=dev` | Alert with the package name |
| S3 | Security | Secret in a log or the repo | Audit 1.1 and 15.2 (exist), now alerting | Alert |
| M1 | Machine | Mac set to sleep | `pmset -g` sleep ≠ 0 on power | Alert with the one command to run (a system setting: the owner runs it) |
| M2 | Machine | Power cut | Uptime < 15 min with a missed snapshot run | Catch-up runs; alert "restarted after a power cut" |
| O1 | Outside | Mac unreachable (power, network, crash) | Oracle VM: 3 failed probes in a row | Alert from outside; a Mac that is down cannot report itself |

The backup list gains every irreplaceable database: `breakouts.db`, the forecast's
`method_choices`, `intraday_forward.db` and `incidents.db` itself.

### 3.3 Remote access

- The owner installs Tailscale on the Mac and the phone and signs in. The dashboard is then at
  `http://<mac-name>:3000` from anywhere.
- `DASHBOARD_HOSTS` gains the tailnet name. The pairing token still guards every non-local request.
- Nothing is published to the internet: no port forwarding and no public URL.
- Kite's login callback: Kite redirects to the URL registered in its developer console. For
  logging in from the phone, the owner adds the tailnet address there.

### 3.4 The Oracle watchdog VM

- **The machine:** an Always Free Ampere A1 instance with 1 OCPU and 6 GB, well inside the free
  2 OCPU and 12 GB. It runs Ubuntu, joins the tailnet, and needs no inbound ports.
- **`watchdog/remote_watch.py`, a single file run by cron every 5 minutes:**
  - probes the Mac's API and web over Tailscale;
  - reads the heartbeat the Mac's watchdog writes there (via rsync);
  - alerts through the same ntfy topic.
- **Backups:** `rsync` receives the Mac's nightly backups into a 30-day rotation, and a weekly
  `quick_check` runs on the newest of each.
- **Install:** `watchdog/install_remote.sh` installs the cron entries and the systemd timer. It is
  idempotent and holds no secrets in the repo.
- **What the VM never does:** call NSE or Kite, or hold the Kite session.

### 3.5 Ready for a server later

- `scripts/install_app_services.sh` gains a Linux path (systemd units mirroring the launchd ones).
- Every `osascript` call goes through `alerts.py`.
- macOS-only checks (M1, keep-awake) are skipped on Linux.
- Moving the app to a server later is then a matter of an install script and a data copy, if NSE
  ever answers from one.

### 3.6 The dashboard

A "System health" line joins the freshness strip: "All checks passing", or the count of open
incidents with the oldest one named. It links to a short list of incidents, each with what it is,
when it opened, the repairs tried, and whether it is resolved. It sits in the freshness strip at the top of the Today tab.

## 4. What the owner does (Claude cannot: accounts, payments, system settings)

1. **Mac power settings, once:** `sudo pmset -c sleep 0 disksleep 0 autorestart 1 womp 1`. This
   means on mains power it never sleeps, and it restarts after a power cut.
2. **Tailscale:** install it on the Mac and the phone and sign in. It is free.
3. **ntfy:** install the app on the phone and subscribe to the private topic name the installer
   prints. It is free and needs no account.
4. **Oracle Cloud:** sign up for Always Free (Oracle asks for a card to verify identity; Always
   Free resources are not charged) and create the VM, then run one install command on it.
5. **Kite developer console:** add the tailnet callback URL, if logging in from the phone is wanted.

## 5. Testing

- Unit tests for every check, with fakes: no disk, a corrupt DB copy, a changed NSE payload, a
  hung server, a missing backup.
- Failure drills, run by hand in a worktree:
  - fill a temp disk;
  - corrupt a copy of a DB;
  - stop the API;
  - change a canary field;
  - land a deliberately broken commit and watch it roll back.
- Alerts are tested against a throwaway ntfy topic. The live topic gets one test message, sent
  when the owner asks.
- Every check reads the real `api/data` read-only. Repairs are tested only on worktree copies.

## 6. Order of work

1. **Phase 1, on the Mac:**
   - `sentinel` (checks, repairs, incidents, alerts) and the catalogue rows that need no new
     services;
   - the backup list completed;
   - the rollback in `land.sh`;
   - the System health line.
2. **Phase 2, remote:** the Tailscale host setting, ntfy alerts, the offsite rsync, and the
   Oracle watchdog with its installer.
3. **Phase 3, portability:** the Linux service units, and `osascript` fully behind `alerts.py`.

Each phase lands on its own with its tests, outside 19:20 to "daily job done".

## 7. Risks and open questions

- **Free capacity:** Oracle's free A1 capacity is not guaranteed in every region. If Mumbai has
  none, any region works, because the watchdog does not call NSE.
- **Idle reclamation:** Oracle may reclaim idle free instances. The watchdog's steady small load
  and the weekly backup check keep it active. If it is reclaimed, the Mac keeps running and only
  the outside view is lost, which the daily digest's silence would reveal.
- **The home connection:** it stays a single point. A 4G phone hotspot as a fallback is a
  hardware choice for the owner.
