"""The new data sources: NSE's all-index report, the Yahoo top-up that keeps
the forward log from losing a day, BSE's SENSEX file, and GIFT Nifty."""

import pandas as pd

import backtest.strategies as strategies
from market_data import gift_nifty, nse_indices
from market_data.nse_bhavcopy import parse_option_bars

NSE_INDEX_FILE = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,"
    "Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
    "Nifty 50,22-09-2026,23454.05,23489,23285.75,23329,-85.3,-.36,1,1,1,1,1\n"
    "Nifty Midcap Select,03-01-2022,-,-,-,7465.92,107.96,1.47,1,1,1,1,1\n")


def test_nse_index_report_is_parsed_and_close_only_days_keep_their_close():
    rows = {r.index_name: r for r in nse_indices.parse(NSE_INDEX_FILE, "2026-09-22")}
    assert rows["Nifty 50"].close == 23329 and rows["Nifty 50"].open == 23454.05
    assert rows["Nifty Midcap Select"].open is None and rows["Nifty Midcap Select"].close == 7465.92
    assert nse_indices.parse("<html>not a csv</html>", "2026-09-22") == []


def _yahoo(last="2026-09-21"):
    idx = pd.to_datetime(pd.bdate_range(end=last, periods=3))
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "provisional": False},
                        index=idx.rename("timestamp"))


def test_every_loader_shares_one_top_up():
    # It used to live in the backtest loader alone, so /api/snapshot and the
    # briefing showed an older session than the rest of the page.
    from quant import pipeline
    assert strategies.nse_top_up is nse_indices.top_up is pipeline.nse_top_up


def test_a_session_yahoo_lacks_is_taken_from_nse(monkeypatch):
    nse = pd.DataFrame({"open": [9.0, 3.0], "high": [9.0, 4.0], "low": [9.0, 2.0], "close": [9.0, 3.5]},
                       index=pd.to_datetime(["2026-09-21", "2026-09-22"]))
    monkeypatch.setattr(nse_indices, "load_archive", lambda u, db_path=None: nse)
    df = strategies._top_up_from_nse(_yahoo(), "^NSEI")
    assert str(df.index[-1].date()) == "2026-09-22" and df["close"].iloc[-1] == 3.5
    assert df.loc["2026-09-21", "close"] == 1.5  # history stays Yahoo's; only later sessions are added
    assert not df["provisional"].iloc[-1]


def test_a_recent_session_missing_in_the_middle_of_yahoo_is_filled_from_nse(monkeypatch):
    """Yahoo dropped 22 Sep 2026: it was in the series the evening it
    happened (NSE topped it up) and gone the next day, when Yahoo returned
    the 23rd without it. Only sessions after Yahoo's last one used to be
    added, so a hole in the middle stayed a hole: the forward log could not
    score that day, the paper book counted its hold a session short, and the
    briefing compared the 23rd with the 21st as "the previous day"."""
    yahoo = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "provisional": False},
                         index=pd.to_datetime(["2025-01-02", "2026-09-18", "2026-09-21", "2026-09-23"]).rename("timestamp"))
    nse = pd.DataFrame({"open": 3.0, "high": 4.0, "low": 2.0, "close": [7.0, 8.0, 3.5, 9.0, 5.0]},
                       index=pd.to_datetime(["2025-01-01", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]))
    monkeypatch.setattr(nse_indices, "load_archive", lambda u, db_path=None: nse)
    df = strategies._top_up_from_nse(yahoo, "^NSEI")
    dates = [str(d.date()) for d in df.index]
    assert dates == ["2025-01-02", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    assert df.loc["2026-09-22", "close"] == 3.5 and not df.loc["2026-09-22", "provisional"]
    # Yahoo's own sessions are never replaced, and the research period is left
    # exactly as it was tested: an old gap (1 Jan 2025) is not filled.
    assert df.loc["2026-09-21", "close"] == 1.5 and df.loc["2026-09-23", "close"] == 1.5
    assert "2025-01-01" not in dates


def test_no_top_up_for_other_symbols_or_close_only_rows(monkeypatch):
    nse = pd.DataFrame({"open": [None], "high": [None], "low": [None], "close": [3.5]},
                       index=pd.to_datetime(["2026-09-22"]))
    monkeypatch.setattr(nse_indices, "load_archive", lambda u, db_path=None: nse)
    assert len(strategies._top_up_from_nse(_yahoo(), "^NSEI")) == 3
    assert len(strategies._top_up_from_nse(_yahoo(), "^GSPC")) == 3


def test_bse_udiff_rows_are_read_like_nse_ones():
    text = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
            "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
            "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
            "2025-09-19,2025-09-19,FO,BSE,IDO,1,,SENSEX,,2025-09-25,2025-09-25,81000.00,PE,X,21.40,39.60,18.00,25.30,"
            "26.20,23.55,82626.23,25.30,365080,77100,4444500,1,1,F1,20,,,,,\n"
            "2025-09-19,2025-09-19,FO,BSE,IDF,2,,SENSEX,,2025-09-25,2025-09-25,,,Y,1,1,1,1,1,1,1,1,1,1,1,1,1,F1,20,,,,,\n")
    bars = parse_option_bars(text, ("SENSEX",))["SENSEX"]
    assert len(bars) == 1 and bars[0].option_type == "PE" and bars[0].close == 25.30  # the future is not an option


def test_gift_nifty_picks_the_nearest_traded_future():
    payload = {"MBP_data_Market_Watch": [
        {"token_data": [{"INSTRUMENTTYPE": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRYDATE": "27-Oct-2026", "VOLUME": 5,
                         "LASTPRICE": "23459.50", "CLOSE": "23437.50", "LTT": "t"}]},
        {"token_data": [{"INSTRUMENTTYPE": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRYDATE": "29-Sep-2026", "VOLUME": 9,
                         "LASTPRICE": "23389", "CLOSE": "23400.00", "LTT": "t"}]},
        {"token_data": [{"INSTRUMENTTYPE": "OPTIDX", "SYMBOL": "NIFTY", "EXPIRYDATE": "22-Sep-2026", "VOLUME": 9,
                         "LASTPRICE": "5", "CLOSE": "6", "LTT": "t"}]}]}
    q = gift_nifty.parse(payload)
    assert q["expiry"] == "2026-09-29" and q["last"] == 23389 and q["change_pct"] == -0.05
    assert gift_nifty.parse({"MBP_data_Market_Watch": []}) is None
