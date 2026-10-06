"""The sentinel's incidents: written once, then only appended to — the same
rule as the forward log, so the record of what broke and what was tried
cannot be tidied after the fact."""

import sqlite3

import pytest

import storage.incidents_db as idb


def test_an_incident_is_written_once_and_only_appended_to(tmp_path):
    db = tmp_path / "i.db"
    i = idb.open_incident("disk", "data", "warn", "4.2 GB free", "2026-10-07T05:00:00+05:30", db)
    idb.add_event(i, "seen", "4.2 GB free", "2026-10-07T05:10:00+05:30", db)
    idb.add_event(i, "seen", "4.1 GB free", "2026-10-07T05:20:00+05:30", db)
    idb.add_event(i, "repair", "tidy_disk: ok, freed 1.2 GB", "2026-10-07T05:20:01+05:30", db)
    (o,) = idb.open_incidents(db)
    assert o["check_key"] == "disk" and o["seen_count"] == 2 and len(o["repairs"]) == 1
    assert o["last_seen"] == "2026-10-07T05:20:00+05:30" and o["last_alert_at"] is None
    assert not [n for n in dir(idb) if n.startswith(("update", "delete"))]
    with pytest.raises(sqlite3.DatabaseError):
        with idb.connect(db) as conn:
            conn.execute("UPDATE incidents SET summary = 'tidied'")
    with pytest.raises(sqlite3.DatabaseError):
        with idb.connect(db) as conn:
            conn.execute("DELETE FROM events")


def test_a_resolved_incident_is_no_longer_open(tmp_path):
    db = tmp_path / "i.db"
    i = idb.open_incident("disk", "data", "warn", "low", "2026-10-07T05:00:00+05:30", db)
    idb.add_event(i, "alert", "open", "2026-10-07T05:00:01+05:30", db)
    assert idb.open_incidents(db)[0]["last_alert_at"] == "2026-10-07T05:00:01+05:30"
    idb.add_event(i, "resolved", "passed twice", "2026-10-07T05:30:00+05:30", db)
    assert idb.open_incidents(db) == []
    assert [r["check_key"] for r in idb.recent(14, db, now="2026-10-07T06:00:00+05:30")] == ["disk"]
