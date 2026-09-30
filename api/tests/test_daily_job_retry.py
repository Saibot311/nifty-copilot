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
    steps = {"options archive": lambda: ran.append(1) or True}
    assert job.retry(["options archive"], steps, job.RETRY_AT_END) == ["options archive"] and ran == []


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
