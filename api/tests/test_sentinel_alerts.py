"""Alerts: to the phone through ntfy when a topic is set, to the Mac always;
one message when an incident opens, a reminder after six hours, one when it
resolves, and a digest once a day — never one every ten minutes."""

from datetime import datetime, timedelta

from market_data.kite_session import IST
from sentinel import alerts

NOW = datetime(2026, 10, 7, 5, 0, tzinfo=IST)


def test_no_topic_means_local_only(monkeypatch):
    monkeypatch.setattr(alerts, "_env", lambda k: None)
    posted, local = [], []
    assert alerts.send("t", "body", post=lambda *a: posted.append(a), local=lambda m: local.append(m)) is False
    assert posted == [] and local == ["t: body"]


def test_a_topic_posts_to_ntfy_and_still_echoes_locally(monkeypatch):
    monkeypatch.setattr(alerts, "_env", lambda k: {"NTFY_TOPIC": "secret-topic"}.get(k))
    posted, local = [], []
    assert alerts.send("Disk low", "4 GB free", "high",
                       post=lambda url, body, headers: posted.append((url, body, headers)) or True,
                       local=lambda m: local.append(m)) is True
    (url, body, headers), = posted
    assert url == "https://ntfy.sh/secret-topic" and body == "4 GB free"
    assert headers["Title"] == "Disk low" and headers["Priority"] == "high" and local


def test_one_open_message_then_a_reminder_after_six_hours():
    inc = {"last_alert_at": None}
    assert alerts.due(inc, NOW) == "open"
    inc = {"last_alert_at": NOW.isoformat()}
    assert alerts.due(inc, NOW + timedelta(minutes=10)) is None
    assert alerts.due(inc, NOW + timedelta(hours=6)) == "reminder"


def test_the_digest_runs_once_a_day_after_0830():
    assert not alerts.digest_due(NOW.replace(hour=8, minute=29), {})
    assert alerts.digest_due(NOW.replace(hour=8, minute=30), {})
    assert not alerts.digest_due(NOW.replace(hour=9), {"digest_on": "2026-10-07"})


def test_the_digest_names_each_open_incident():
    assert alerts.digest_text([]) == "All checks passing."
    t = alerts.digest_text([{"summary": "4 GB free", "opened_at": "2026-10-07T05:00:00+05:30"},
                            {"summary": "NSE refused", "opened_at": "2026-10-06T10:15:00+05:30"}])
    assert t == "2 open: 4 GB free (since 05:00 7 Oct); NSE refused (since 10:15 6 Oct)"
