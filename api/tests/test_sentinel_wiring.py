"""The sentinel wired in: the watchdog starts the fast check, the nightly job
runs the deep one after the audit, and the API serves incidents without ever
returning the alert topic."""

import importlib.util
import inspect
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_api_serves_incidents_without_the_topic(monkeypatch, tmp_path):
    import main
    import storage.incidents_db as idb
    monkeypatch.setattr(idb, "DB_PATH", tmp_path / "i.db")
    idb.open_incident("disk", "data", "warn", "4 GB free", "2026-10-07T05:00:00+05:30", tmp_path / "i.db")
    monkeypatch.setattr("sentinel.alerts._env", lambda k: "my-secret-topic" if k == "NTFY_TOPIC" else None)
    monkeypatch.setattr(main, "_sentinel_state", lambda: {"checked_at": "2026-10-07T05:10:00+05:30"})
    r = main.sentinel()
    assert r["open"][0]["summary"] == "4 GB free" and r["ntfy"] is True
    assert "my-secret-topic" not in str(r)


def test_the_job_runs_the_deep_check_after_the_audit():
    src = inspect.getsource(_load("daily_job"))
    assert src.index('("audit", step_audit)') < src.index('("sentinel deep check", step_sentinel)')


def test_the_watchdog_starts_the_fast_check():
    assert 'sentinel_run.py"), "--mode", "fast"' in inspect.getsource(_load("health_watch"))


def test_the_runner_filters_by_mode_and_writes_its_result(tmp_path, monkeypatch):
    from sentinel import core
    run = _load("sentinel_run")
    seen = {}
    monkeypatch.setattr(run, "all_checks", lambda: ["c"])
    monkeypatch.setattr(core, "run", lambda mode, checks, now, **kw: seen.update(mode=mode, checks=checks) or
                        {"checked": 1, "failing": [], "opened": [], "resolved": []})
    monkeypatch.setattr(run, "OUT", tmp_path / "sentinel.json")
    monkeypatch.setattr(run, "send_digest_if_due", lambda now: None)
    assert run.main(["--mode", "deep"]) == 0
    assert seen == {"mode": "deep", "checks": ["c"]} and (tmp_path / "sentinel.json").exists()


def test_the_api_reads_the_last_run_from_disk(monkeypatch, tmp_path):
    import json

    import main
    out = tmp_path / "data"
    out.mkdir()
    (out / "sentinel.json").write_text(json.dumps({"checked_at": "2026-10-07T05:10:00+05:30", "mode": "fast"}))
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    assert main._sentinel_state()["mode"] == "fast"
