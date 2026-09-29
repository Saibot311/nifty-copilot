"""The Market tab's indices board: NIFTY, Bank Nifty and Sensex, with GIFT
Nifty beside them, and a commentary written in Python from the numbers —
what moved and how, never what to do about it."""

from datetime import datetime

from market_data import indices_board as ib

NOW = datetime.fromisoformat("2026-09-25T11:05+05:30")

NSE = {"market_time": "2026-09-25T11:05+05:30",
       "rows": {"NIFTY 50": {"last": 23140.5, "previous_close": 23063.1, "open": 23100.0, "high": 23150.0,
                             "low": 23010.0},
                "NIFTY BANK": {"last": 55380.4, "previous_close": 55438.5, "open": 55450.0, "high": 55600.0,
                               "low": 55300.0}}}
SENSEX = {"last": 73895.7, "previous_close": 73580.5, "open": 73600.0, "high": 73950.0, "low": 73500.0,
          "as_of": "2026-09-25T11:04+05:30"}
GIFT = {"last": 23237.5, "previous_close": 23188.5, "change_pct": 0.21, "high": 23248.5, "low": 23056.5,
        "open": 23106.0, "last_trade_time": "25-Sep-2026 11:04:57"}


def test_rows_carry_level_change_and_their_own_time():
    b = ib.board(NSE, SENSEX, GIFT, market_open=True, now=NOW)
    by = {r["key"]: r for r in b["rows"]}
    assert list(by) == ["nifty", "banknifty", "sensex", "gift"]
    assert by["nifty"]["change_pct"] == 0.34 and by["banknifty"]["change_pct"] == -0.10
    assert by["sensex"]["as_of"] == "2026-09-25T11:04+05:30"
    assert by["gift"]["as_of"] == "2026-09-25T11:04:57+05:30"
    assert by["nifty"]["day_position"] == 93                   # (23140.5 - 23010) / 140


def test_commentary_describes_the_moves_in_words_python_chose():
    lines = ib.board(NSE, SENSEX, GIFT, market_open=True, now=NOW)["commentary"]
    text = " ".join(lines)
    assert "Mixed" in text and "Bank Nifty down" in text
    assert "Bank Nifty is lagging NIFTY: −0.10% against +0.34%" in text
    assert "NIFTY is near the day's high" in text
    for word in ("buy", "sell", "should", "will ", "expect", "target"):
        assert word not in text.lower()


def test_after_hours_gift_is_context_not_a_forecast():
    shut = {**NSE, "market_time": "2026-09-25T15:30+05:30"}
    gift = {**GIFT, "last_trade_time": "25-Sep-2026 21:14:05"}
    lines = ib.board(shut, SENSEX, gift, market_open=False, now=datetime.fromisoformat("2026-09-25T21:20+05:30"))["commentary"]
    g = next(x for x in lines if x.startswith("GIFT"))
    assert "+0.21%" in g and "21:14" in g and "not a forecast" in g


def test_a_missing_feed_is_left_out_and_said_so():
    b = ib.board(NSE, None, GIFT, market_open=True, now=NOW)
    assert [r["key"] for r in b["rows"]] == ["nifty", "banknifty", "gift"]
    assert any("Sensex" in x and "not available" in x for x in b["commentary"])


def test_a_row_minutes_behind_the_rest_is_flagged_in_a_session():
    late = {**SENSEX, "as_of": "2026-09-25T10:51+05:30"}
    b = ib.board(NSE, late, GIFT, market_open=True, now=NOW)
    assert {r["key"]: r for r in b["rows"]}["sensex"]["behind"] is True
    assert any("Sensex" in x and "10:51" in x for x in b["commentary"])


def test_a_gift_nifty_that_has_stopped_trading_is_not_called_trading():
    from datetime import datetime
    shut = {**NSE, "market_time": "2026-09-25T15:30+05:30"}
    gift = {**GIFT, "last_trade_time": "26-Sep-2026 02:39:57"}
    lines = ib.board(shut, SENSEX, gift, market_open=False,
                     now=datetime.fromisoformat("2026-09-26T10:00+05:30"))["commentary"]
    g = next(x for x in lines if x.startswith("GIFT"))
    assert "last traded at 02:39 IST on 26 Sep" in g and "is trading" not in g



# --- Sensex: Kite first -------------------------------------------------------

def _kite_quote(monkeypatch, ts):
    from market_data import kite_quotes as kq

    class Client:
        def quote(self, keys):
            assert keys == ["BSE:SENSEX"]
            return {"BSE:SENSEX": {"last_price": 72771.72, "timestamp": ts, "net_change": -1124.02,
                                   "ohlc": {"open": 73734.83, "high": 73740.85, "low": 72716.23, "close": 73895.74}}}
    monkeypatch.setattr(kq, "authenticated_client", Client)
    monkeypatch.setattr(kq, "_quote_slot", lambda: None)
    return kq


def test_sensex_comes_from_kite_with_bses_own_open(monkeypatch):
    """Yahoo's one-minute bars gave the day's high (73,740.85) as the open on
    28 Sep 2026; Kite's quote has BSE's figures."""
    _kite_quote(monkeypatch, datetime(2026, 9, 28, 11, 2, 7))
    s = ib._sensex()
    assert s == {"last": 72771.72, "previous_close": 73895.74, "open": 73734.83, "high": 73740.85,
                 "low": 72716.23, "as_of": "2026-09-28T11:02+05:30", "source": "Kite"}
    row = ib.board(None, s, None, market_open=True)["rows"][0]
    assert row["source"] == "Kite" and row["change_pct"] == round((72771.72 / 73895.74 - 1) * 100, 2)


def test_after_the_close_kites_later_stamps_are_shown_as_the_close_they_repeat(monkeypatch):
    _kite_quote(monkeypatch, datetime(2026, 9, 28, 17, 30, 2))
    assert ib._sensex()["as_of"] == "2026-09-28T15:30+05:30"


def test_without_a_kite_login_sensex_falls_back_to_yahoo(monkeypatch):
    from market_data import kite_quotes as kq

    def lapsed():
        raise RuntimeError("Kite login has lapsed")
    monkeypatch.setattr(kq, "authenticated_client", lapsed)
    monkeypatch.setattr(kq, "_quote_slot", lambda: None)
    monkeypatch.setattr(ib, "_sensex_yahoo", lambda: {"last": 1.0, "previous_close": 1.0, "source": "Yahoo, 1-min bars"})
    assert ib._sensex()["source"] == "Yahoo, 1-min bars"


def test_kite_quote_calls_are_spaced_a_second_apart(monkeypatch):
    """The tick and the board call Kite's quote APIs from their own threads;
    Kite refuses more than one call a second."""
    from market_data import kite_quotes as kq
    clock = {"t": 1000.0}
    slept = []
    monkeypatch.setattr(kq.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(kq.time, "sleep", lambda s: slept.append(round(s, 2)))
    monkeypatch.setitem(kq._LAST_CALL, "at", 0.0)
    kq._quote_slot()
    clock["t"] += 0.3
    kq._quote_slot()
    assert slept == [0.7]
