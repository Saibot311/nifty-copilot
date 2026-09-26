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
