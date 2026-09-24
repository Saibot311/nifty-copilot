"""The live path: what the dashboard is told when a source is slow, down, or
all of them are.

NSE's client library sends every request without a timeout — including the
cookie handshake it makes on construction. A socket NSE stops answering on
therefore blocked its caller forever, and because the tick endpoint's cache
hands everyone else the last value while one thread refreshes, the price,
the market status and the option chain froze with nothing saying so.
"""

import socket
import threading
import time

import pytest

import market_data.live_quote as lq


@pytest.fixture
def blackhole():
    """A server that accepts connections and never says a word."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    held = []
    stop = threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])
            except OSError:
                pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}/"
    stop.set()
    for c in held:
        c.close()
    srv.close()


def test_a_silent_nse_cannot_block_the_session_forever(blackhole, monkeypatch):
    import jugaad_data.nse.live as live

    monkeypatch.setattr(live.NSELive, "page_url", blackhole)
    monkeypatch.setattr(lq, "NSE_TIMEOUT_S", 0.5, raising=False)
    monkeypatch.setattr(lq, "_SESSION", None)
    outcome = {}

    def build():
        try:
            lq._session()
            outcome["result"] = "answered"
        except Exception as e:  # a timeout is the right answer here
            outcome["result"] = type(e).__name__

    t = threading.Thread(target=build, daemon=True)
    started = time.monotonic()
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "the NSE handshake is still waiting on a silent socket"
    assert "Timeout" in outcome["result"] and time.monotonic() - started < 5


# --- the tick: every price says where it came from and how old it is ---------

@pytest.fixture
def tick(monkeypatch):
    import cache
    import main
    from briefing import paper

    cache.invalidate()
    monkeypatch.setattr(main, "_previous_close", lambda: 23446.8)
    monkeypatch.setattr(main, "_last_close", lambda: ("2026-09-24", 23063.1), raising=False)
    monkeypatch.setattr(main, "market_status", lambda: {"is_open": True, "status": "Open"})
    state = {}

    def run(kite=None, nse=None, status=None):
        def marks():
            if isinstance(kite, Exception):
                raise kite
            return kite
        def quote(index="NIFTY 50"):
            if isinstance(nse, Exception) or nse is None:
                raise nse or RuntimeError("no NSE")
            return nse
        monkeypatch.setattr(paper, "live_marks", marks)
        monkeypatch.setattr(main, "live_index_quote", quote)
        if status is not None:
            monkeypatch.setattr(main, "market_status", status)
        cache.invalidate()
        return main.live_tick()
    yield run
    cache.invalidate()


def test_kite_first_with_its_time(tick):
    from datetime import datetime
    at = datetime.now(lq.IST).isoformat(timespec="seconds")
    t = tick(kite={"index": 23100.0, "source": "Kite (live)", "quote_at": at, "marks": {}, "paper": None})
    assert t["source"] == "Kite (live)" and t["index"] == 23100.0
    assert t["quote_at"] == at and t["stale"] is False and t["age_s"] < 5
    assert t["change"] == round(23100.0 - 23446.8, 2)


def test_nse_when_kite_is_down_and_its_age_is_passed_on(tick):
    t = tick(kite=RuntimeError("not logged in"),
             nse={"last": 23090.0, "change": -356.8, "change_pct": -1.52, "source": "NSE live feed",
                  "fetched_at": "2026-09-24T14:30:00+05:30", "age_s": 130.0, "stale": True})
    assert t["source"] == "NSE live feed" and t["index"] == 23090.0
    # NSE's last good price, served because the refresh failed, says so.
    assert t["stale"] is True and t["age_s"] == 130.0 and t["quote_at"] == "2026-09-24T14:30:00+05:30"


def test_last_close_when_both_are_down_labelled_as_such(tick):
    t = tick(kite=RuntimeError("down"), nse=RuntimeError("down"))
    assert t["source"] == "last close" and t["index"] == 23063.1
    assert t["quote_at"].startswith("2026-09-24") and t["stale"] is True
    assert t.get("change") is None  # no move is computed against a price that is not live


def test_an_unknown_market_status_is_not_reported_as_closed(tick):
    def down():
        raise RuntimeError("NSE unreachable")
    t = tick(kite={"index": 23100.0, "source": "Kite (live)", "quote_at": "2026-09-24T11:00:00+05:30",
                   "marks": {}, "paper": None}, status=down)
    assert t["market"]["is_open"] is None and t["market"]["status"] == "unknown"
    assert t["market"]["open_by_clock"] in (True, False)


def test_the_clock_fallback_knows_the_session_hours():
    from datetime import datetime
    ist = lq.IST
    assert lq.open_by_clock(datetime(2026, 9, 24, 11, 0, tzinfo=ist)) is True      # Thursday, mid-session
    assert lq.open_by_clock(datetime(2026, 9, 24, 9, 14, tzinfo=ist)) is False     # pre-open
    assert lq.open_by_clock(datetime(2026, 9, 24, 15, 30, tzinfo=ist)) is False    # the close
    assert lq.open_by_clock(datetime(2026, 9, 26, 11, 0, tzinfo=ist)) is False     # Saturday
