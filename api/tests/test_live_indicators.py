"""The indicator grid under the Today chart: only readings that work, and
they move with the market.

Relative volume and VWAP are gone: an index has no traded volume on the free
feed, so they showed "0.0x" and "Unavailable" every day. The rest used to be
computed from yesterday's close all session; now, while NSE reports a
session newer than the last daily candle, its open/high/low/last become a
provisional candle and every reading includes it."""

import numpy as np
import pandas as pd
import pytest

from briefing import live_indicators as li

IDX = pd.bdate_range(end="2026-09-24", periods=300)


@pytest.fixture
def world(monkeypatch):
    close = pd.Series(23000 + np.cumsum(np.random.default_rng(5).normal(0, 70, len(IDX))), index=IDX)
    df = pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]), "high": close + 60, "low": close - 60,
                       "close": close, "volume": 0.0})
    monkeypatch.setattr(li, "_frame", lambda: df)
    monkeypatch.setattr(li, "_chain_iv", lambda: {"iv": 11.9, "as_of": "24-Sep-2026 15:40:00"})
    state = {"quote": {"open": 23221.8, "high": 23281.95, "low": 23046.15, "last": float(close.iloc[-1]),
                       "india_vix": 12.7, "india_vix_change_pct": 3.4, "market_time": "2026-09-24T15:30+05:30"},
             "open": False}
    monkeypatch.setattr(li, "_quote", lambda: state["quote"])
    monkeypatch.setattr(li, "_is_open", lambda: state["open"])
    return df, state


def test_broken_readings_are_gone_and_every_tile_says_when_it_is_from(world):
    out = li.live_indicators()
    names = [t["name"] for t in out["tiles"]]
    assert not any("Volume" in n or "VWAP" in n for n in names)
    assert all(t["value"] and t["as_of"] for t in out["tiles"])
    assert out["live"] is False and out["basis"] == "As of the 24 Sep close"


def test_in_a_session_today_is_a_provisional_candle_in_every_reading(world):
    from quant.indicators import rsi
    df, state = world
    state["open"] = True
    state["quote"] = {**state["quote"], "open": 23100.0, "high": 23180.0, "low": 22990.0, "last": 23150.0,
                      "market_time": "2026-09-25T11:05+05:30"}
    out = li.live_indicators()
    assert out["live"] is True and "25 Sep so far · 11:05 IST" in out["basis"]
    with_today = pd.concat([df["close"], pd.Series([23150.0], index=[pd.Timestamp("2026-09-25")])])
    rsi_tile = next(t for t in out["tiles"] if t["key"] == "rsi")
    assert rsi_tile["value"] == f"{float(rsi(with_today).iloc[-1]):.1f}"
    rng = next(t for t in out["tiles"] if t["key"] == "range")
    assert "190" in rng["value"]                           # 23,180 - 22,990 so far today


def test_no_iv_is_shown_as_unavailable_not_zero(world, monkeypatch):
    monkeypatch.setattr(li, "_chain_iv", lambda: {"iv": None, "as_of": None})
    tile = next(t for t in li.live_indicators()["tiles"] if t["key"] == "iv_vs_hv")
    assert tile["value"] == "not available" and "0.0" not in tile["detail"]


def test_negative_figures_carry_a_real_minus(world):
    out = li.live_indicators()
    blob = " ".join(t["value"] + " " + t["detail"] for t in out["tiles"])
    assert "-" not in blob.replace("Prev-", "").replace("-day", "").replace("20-", "").replace("14-", "")


def test_after_the_close_a_session_the_daily_file_lacks_is_still_counted(world):
    _, state = world
    state["quote"] = {**state["quote"], "open": 23100.0, "high": 23180.0, "low": 22990.0, "last": 23150.0,
                      "market_time": "2026-09-25T15:30+05:30"}
    out = li.live_indicators()
    assert out["live"] is False and out["session"] == "2026-09-25"
    assert out["basis"] == "As of the 25 Sep close · NSE live feed"


def test_pre_open_zeros_are_not_a_candle(world):
    df, state = world
    state["open"] = True
    state["quote"] = {**state["quote"], "open": 0, "high": 0, "low": 0, "last": 23150.0,
                      "market_time": "2026-09-25T09:08+05:30"}
    out = li.live_indicators()
    assert out["session"] == "2026-09-24" and out["live"] is False
