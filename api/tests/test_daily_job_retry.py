"""A step that failed because the network dropped gets one more try at the
end of the nightly job; the rest are reported as they were."""

import importlib.util
from pathlib import Path


def _job():
    spec = importlib.util.spec_from_file_location("daily_job", Path(__file__).parents[1] / "scripts" / "daily_job.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.log = lambda *_: None
    return mod


def test_the_forward_log_is_retried_and_cleared_when_it_goes_through():
    job = _job()
    calls = []
    steps = {"forward log": lambda: calls.append(1) or True, "audit": lambda: False}
    assert job.retry(["forward log", "audit"], steps, job.RETRY_AT_END) == ["audit"]
    assert calls == [1]


def test_a_retry_that_fails_again_stays_failed():
    job = _job()

    def boom():
        raise ConnectionError("asleep")
    assert job.retry(["forward log"], {"forward log": boom}, job.RETRY_AT_END) == ["forward log"]


def test_steps_not_named_are_not_rerun():
    job = _job()
    ran = []
    steps = {"audit": lambda: ran.append(1) or True}
    assert job.retry(["audit"], steps, job.RETRY_AT_END) == ["audit"] and ran == []


def test_a_network_drop_mid_job_is_made_up_at_the_end():
    """28 Sep 2026: the network dropped for a moment at 19:42. Yahoo returned
    no bars and every news feed failed, so four research studies, the news
    archive and the tone series lost the night, although the network was
    back well before the job ended."""
    job = _job()
    names = ["news archive and judging", "news tone series", "pattern -> option research", "implied volatility",
             "participant positioning", "structural hypotheses", "replication on other indices",
             "news hypotheses", "market context studies"]
    ran = []
    steps = {n: (lambda n=n: ran.append(n) or True) for n in names}
    assert job.retry(names, steps, job.RETRY_AT_END) == []
    assert ran == names          # in the job's own order: positioning before the studies that read it


def test_the_news_step_fails_when_every_feed_failed(monkeypatch):
    import news.feed as feed
    job = _job()
    monkeypatch.setattr(feed, "refresh", lambda judge: {"new": 0, "fetched": 0, "judged": 0,
                                                        "failed": ["rbi", "et_markets"]})
    assert job.step_news() is False
    monkeypatch.setattr(feed, "refresh", lambda judge: {"new": 3, "fetched": 40, "judged": 3, "failed": ["rbi"]})
    assert job.step_news() is True


def test_the_index_report_is_retried_before_the_forward_log_that_needs_its_close():
    """29 Sep 2026: with the network down at 19:30, the index report failed and
    was not retried, so the forward log's second try still had no close for
    the 29th. Everything that reaches the network now gets a second try."""
    job = _job()
    order = job.RETRY_AT_END
    assert order.index("NSE index report") < order.index("forward log")
    assert {"kite bars", "options archive", "other index options"} <= set(order)


def test_the_forward_log_step_fails_when_the_last_session_is_not_the_one_recorded(monkeypatch):
    import briefing.forward_log as fl
    import briefing.recommendation as rec
    job = _job()
    monkeypatch.setattr(rec, "build_recommendation", lambda: {"as_of": "2026-09-28", "action": "NO_TRADE"})
    monkeypatch.setattr(fl, "record_if_final", lambda r: False)
    monkeypatch.setattr(job, "last_session", lambda: "2026-09-29")
    assert job.step_forward_log() is False
    monkeypatch.setattr(job, "last_session", lambda: "2026-09-28")
    assert job.step_forward_log() is True


def test_a_forecast_that_could_not_be_written_is_retried_after_what_it_reads():
    """5 Oct 2026: Monday's close and IV arrived only in the end-of-job retries,
    after the forecast step had already run and written nothing."""
    order = _job().RETRY_AT_END
    assert "day-ahead forecast" in order
    for before in ("NSE index report", "kite bars", "options archive", "implied volatility"):
        assert order.index(before) < order.index("day-ahead forecast")
