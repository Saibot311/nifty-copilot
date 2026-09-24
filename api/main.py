from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import access
from access import TokenGate
from typing import Literal

from pydantic import BaseModel, Field

from backtest.research import run_all_strategies
from cache import cached
from backtest.walkforward import evaluate_strategy
from backtest.intraday import load_research as load_intraday_research
from backtest.iv_research import load_iv_research, load_series as load_iv_series
from backtest.structural_research import load_structural_research
from briefing.journal import report as journal_report, system_action_for
from storage import journal_db, login_log_db
from market_engine.engine import load_studies as load_market_studies, today as market_today
from market_engine.knowledge import KNOWLEDGE
from backtest.pattern_options import load_research
from backtest.pattern_proximity import pattern_proximity
from backtest.live_patterns import live_patterns, merge_live
from backtest.similarity import run_similarity
from copilot import assistant as copilot
from copilot.llm_client import LLMError, LLMNotConfigured, config as llm_config
from copilot.jev import available as jev_available
from storage.copilot_log_db import summary as copilot_record_summary
from briefing import build_briefing, build_recommendation
from briefing.forward_log import forward_report, record_if_final
from options.chain_analytics import live_chain_analytics
from storage import archive_stats, record_strategy_evaluation, strategy_history, strategy_playbook
from market_data import Candle, CSVProvider, YFinanceProvider, ZerodhaProvider
from market_data import kite_session
from market_data.bar_archive import ArchiveProvider, archive_summary
from market_data.live_quote import live_index_quote, market_status, open_by_clock
from quant import build_analysis

app = FastAPI(title="NIFTY Copilot API")


def _allowed_origins() -> list[str]:
    """This Mac, both spellings — a browser opened at 127.0.0.1 sends that as
    its origin and every client-side fetch fails CORS if only "localhost" is
    listed. Plus this Mac's own addresses when the dashboard is deliberately
    reachable from a phone (DASHBOARD_HOSTS in api/.env, set by
    install_app_services.sh --lan). Never a wildcard."""
    origins = [f"http://{h}:3000" for h in ("localhost", "127.0.0.1")]
    extra = access._env("DASHBOARD_HOSTS") or ""
    for host in (h.strip() for h in extra.split(",") if h.strip()):
        origins += [f"http://{host}:3000", f"https://{host}:3000"]
    return origins

# Only NIFTY 50 is researched. Every endpoint that takes a symbol is limited
# to it, so malformed input is refused up front (422) instead of being passed
# to Yahoo and failing as a 503 — or quietly fetching some other market.
SUPPORTED_SYMBOL = "^NSEI"
SymbolQuery = Query(SUPPORTED_SYMBOL, pattern=r"^\^NSEI$")

SAMPLE_CSV = Path(__file__).parent / "market_data" / "sample_data" / "nifty_synthetic_15m.csv"

PROVIDERS = {
    "csv": CSVProvider(SAMPLE_CSV),
    "yfinance": YFinanceProvider(),
    "zerodha": ZerodhaProvider(),
    "archive": ArchiveProvider(),
}

# Phase 3: only the Next.js dev server needs access, and only during local development.
# Anything that is not this Mac must present the token (access.py). Added
# before CORS so the browser still gets its headers on a refusal.
app.add_middleware(TokenGate, allowed_origins=_allowed_origins())

app.add_middleware(
    CORSMiddleware,
    # Both spellings of this Mac: a browser opened at 127.0.0.1 sends that as
    # its origin, and every client-side fetch (the live tick, the journal,
    # the paper book) fails CORS if only "localhost" is listed. Nothing else
    # is admitted — this is not going on a network.
    allow_origins=_allowed_origins(),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


class Snapshot(BaseModel):
    symbol: str
    price: float
    change: float
    change_pct: float
    as_of: str
    provisional: bool
    regime: str


class Indicator(BaseModel):
    name: str
    value: str
    read: str  # "supports" | "conflicts" | "neutral"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/deep")
def health_deep() -> dict[str, str]:
    """For the watchdog. /health opens nothing, so it kept answering while
    the API had run out of file descriptors and every real endpoint — each
    one opens a database — was failing. This one has to open a file."""
    import tempfile
    try:
        with tempfile.TemporaryFile() as f:
            f.write(b"ok")
    except OSError as e:
        raise HTTPException(503, f"cannot open a file: {e.strerror or e}")
    return {"status": "ok"}


def _get_analysis() -> dict:
    try:
        return build_analysis()
    except Exception as e:
        raise HTTPException(503, f"Could not fetch/compute live analysis: {e}")


@app.get("/api/snapshot", response_model=Snapshot)
def get_snapshot() -> Snapshot:
    analysis = _get_analysis()
    return Snapshot(
        symbol="NIFTY 50",
        price=analysis["price"],
        change=analysis["change"],
        change_pct=analysis["change_pct"],
        as_of=f"{analysis['as_of'][:10]} daily close (free feed — not live intraday)",
        provisional=False,
        regime=analysis["regime"],
    )


@app.get("/api/indicators", response_model=list[Indicator])
def get_indicators() -> list[Indicator]:
    ind = _get_analysis()["indicators"]
    rows = [
        Indicator(
            name="EMA 20 vs EMA 50",
            value=f"EMA20 {'above' if ind['ema_20'] > ind['ema_50'] else 'below'} EMA50 ({ind['ema_20']} / {ind['ema_50']})",
            read="supports" if ind["ema_20"] > ind["ema_50"] else "conflicts",
        ),
        Indicator(
            name="RSI (14)",
            value=str(ind["rsi_14"]) if ind["rsi_14"] is not None else "n/a",
            read="supports" if (ind["rsi_14"] or 0) > 55 else "conflicts" if (ind["rsi_14"] or 100) < 45 else "neutral",
        ),
        Indicator(
            name="ADX (14)",
            value=f"{ind['adx_14']} ({'trending' if ind['adx_14'] >= 25 else 'not trending'})",
            read="supports" if ind["adx_14"] >= 25 else "neutral",
        ),
        Indicator(
            name="ATR (14)",
            value=f"{ind['atr_14']} pts" if ind["atr_14"] is not None else "n/a",
            read="neutral",
        ),
        Indicator(
            name="Historical Volatility (20d, annualized)",
            value=f"{ind['historical_volatility_pct']}%" if ind["historical_volatility_pct"] is not None else "n/a",
            read="neutral",
        ),
        Indicator(
            name="India VIX",
            value=str(ind["india_vix"]) if ind["india_vix"] is not None else "n/a",
            read="neutral",
        ),
        Indicator(
            name="Relative Volume",
            value=(
                f"{ind['relative_volume']}x (⚠ index has no real volume — not reliable)"
                if ind["relative_volume"] is not None
                else "n/a (index has no real volume)"
            ),
            read="neutral",
        ),
        Indicator(
            name="VWAP",
            value=(
                f"{ind['vwap']['value']} ({ind['vwap']['price_vs_vwap_pct']:+.2f}% vs price)"
                if ind["vwap"] and ind["vwap"]["value"] is not None
                else "Unavailable — index reports 0 intraday volume for free tier"
            ),
            read="neutral",
        ),
    ]
    return rows


@app.get("/api/candles")
def get_candles(
    provider: str = Query("yfinance", description="csv | yfinance | zerodha | archive"),
    symbol: str = SymbolQuery,
    timeframe: str = Query("1d", description="1d | 1h | 15m | 5m (csv provider ignores this)"),
    days: int = Query(30, ge=1, le=3650),
) -> dict:
    """Real (or clearly-labeled synthetic) OHLC candles via the market-data
    abstraction layer. Swapping `provider` swaps the data source entirely —
    nothing else about this endpoint or the rest of the app changes."""
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}'. Choose one of {list(PROVIDERS)}.")

    end = date.today()
    start = end - timedelta(days=days)
    try:
        candles: list[Candle] = PROVIDERS[provider].get_ohlc(symbol, timeframe, start, end)
    except kite_session.KiteNotConfigured as e:
        raise HTTPException(503, str(e))
    except kite_session.KiteNotLoggedIn as e:
        raise HTTPException(401, f"Zerodha session not active: {e}. Visit /api/zerodha/login.")

    return {
        "provider": provider,
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
    }


@app.get("/api/research/compare")
def research_compare(
    symbol: str = SymbolQuery,
    days: int = Query(7000, ge=100, le=10000),
    hold_days: int = Query(10, ge=1, le=60),
) -> dict:
    """Phase 7: runs every strategy in the registry over the same real
    data with the same costs — a fair side-by-side comparison, not a
    search for whichever one looks best. Every run is logged to the
    hypothesis log regardless of outcome."""
    # Cached: this is 26 full backtests (~10s) on daily bars that change once
    # a day. It used to run inside every dashboard render — which waited for
    # it — and append 26 rows to the hypothesis log each time.
    try:
        return cached(f"research_compare:{symbol}:{days}:{hold_days}", ttl_seconds=6 * 3600,
                      producer=lambda: run_all_strategies(symbol=symbol, days=days, hold_days=hold_days),
                      stale_ok=True)
    except Exception as e:
        raise HTTPException(503, f"Research run failed: {e}")


@app.get("/api/validation/{strategy_name}")
def validate_strategy(
    strategy_name: str,
    symbol: str = SymbolQuery,
    days: int = Query(7000, ge=100, le=10000),
    hold_days: int = Query(10, ge=1, le=60),
    n_folds: int = Query(5, ge=2, le=10),
    train_frac: float = Query(0.7, gt=0.3, lt=0.95),
    persist: bool = Query(True, description="Record this verdict to the Phase 9 strategy playbook"),
) -> dict:
    """Phase 8: walk-forward folds + a development/holdout split, combined
    into one honest APPROVED / CONDITIONAL / REJECTED verdict, for any
    strategy in the registry (originally hardcoded to EMA Pullback only).
    Deliberately stricter than either check alone — see the
    methodology_note for the real limitation in what this can and can't
    prove. Persists the verdict to the strategy playbook by default."""
    try:
        result = evaluate_strategy(
            strategy_name=strategy_name, symbol=symbol, days=days,
            hold_days=hold_days, n_folds=n_folds, train_frac=train_frac,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(503, f"Validation run failed: {e}")

    if persist:
        try:
            record_strategy_evaluation(
                result, params={"symbol": symbol, "days": days, "hold_days": hold_days, "n_folds": n_folds, "train_frac": train_frac}
            )
        except Exception:
            pass  # persistence failure shouldn't break the response the caller is waiting on

    return result


@app.get("/api/strategies/playbook")
def strategies_playbook() -> dict:
    """The Strategy Playbook: the latest known validation status for every
    strategy that has ever been evaluated -- a persistent record, not a
    live recomputation. Ranked by expectancy, but status (APPROVED /
    CONDITIONAL / REJECTED) is what actually matters."""
    try:
        return {"strategies": strategy_playbook()}
    except Exception as e:
        raise HTTPException(503, f"Playbook unavailable: {e}")


@app.get("/api/strategies/{strategy_name}/history")
def strategy_history_endpoint(strategy_name: str, limit: int = Query(50, ge=1, le=500)) -> dict:
    """Every recorded validation verdict for one strategy over time, most
    recent first -- lets you see whether a status has been stable or
    drifting, which a single live-recomputed check can never show."""
    try:
        return {"strategy": strategy_name, "history": strategy_history(strategy_name, limit=limit)}
    except Exception as e:
        raise HTTPException(503, f"History unavailable: {e}")


@app.get("/api/briefing")
def research_briefing(
    symbol: str = SymbolQuery,
    include_live_chain: bool = Query(True),
) -> dict:
    """Everything the system knows, assembled: market state, indicator
    readings, rule-based evidence for and against, confirmation and
    invalidation levels, signal status with its honest validation record,
    and live option-chain measurements. Every figure is computed by Python;
    nothing here is estimated."""
    try:
        return build_briefing(symbol=symbol, include_live_chain=include_live_chain)
    except Exception as e:
        raise HTTPException(503, f"Briefing failed: {e}")


@app.get("/api/options/chain")
def options_chain(
    # Only NIFTY: any other value used to open a new cache entry and a new
    # NSE request per spelling.
    symbol: str = Query("NIFTY", pattern=r"^NIFTY$"),
    expiry: str | None = Query(None, pattern=r"^\d{2}-[A-Za-z]{3}-\d{4}$",
                               description="e.g. 22-Sep-2026; defaults to nearest"),
) -> dict:
    """Live NIFTY option chain analytics from NSE — PCR, open-interest
    concentrations, the strike ladder, ATM implied volatility. Measurements,
    not signals: none of these have been backtested on NIFTY yet.

    Cached and stale-tolerant. Open interest is published on a delay and
    barely moves minute to minute, so there is nothing to gain from asking
    NSE once per open dashboard — and plenty to lose: a request per tab is
    what got this machine throttled before."""
    try:
        return cached(f"option_chain:{symbol}:{expiry or 'near'}", ttl_seconds=120,
                      producer=lambda: live_chain_analytics(symbol=symbol, expiry=expiry),
                      stale_ok=True)
    except Exception as e:
        raise HTTPException(503, f"Live option chain unavailable: {e}")


@app.get("/api/options/archive")
def options_archive_status() -> dict:
    """How much of the local NSE options archive has been backfilled."""
    try:
        return archive_stats()
    except Exception as e:
        raise HTTPException(503, f"Archive status unavailable: {e}")


@app.get("/api/live")
def live_quote() -> dict:
    """Current NIFTY price from NSE's live feed, plus whether the market is
    actually open — a 'live' price outside session hours is just the last
    close wearing a live label, so the caller needs to know which it is."""
    try:
        quote = live_index_quote()
        quote["market"] = market_status()
        return quote
    except Exception as e:
        raise HTTPException(503, f"Live quote unavailable: {e}")


@app.get("/api/recommendation")
def recommendation(symbol: str = SymbolQuery) -> dict:
    """Today's call, put, or no-trade verdict across every tested strategy
    in both directions. Will say NO_TRADE unless a signal clears a real
    expectancy and sample-size bar — that is the intended behaviour."""
    try:
        return cached(
            f"recommendation:{symbol}",
            ttl_seconds=600,
            producer=lambda: _build_and_log_recommendation(symbol),
        )
    except Exception as e:
        raise HTTPException(503, f"Recommendation failed: {e}")


def _build_and_log_recommendation(symbol: str) -> dict:
    rec = build_recommendation(symbol=symbol)
    try:
        rec["forward_logged"] = record_if_final(rec, symbol)
    except Exception as e:
        rec["forward_logged"] = False
        rec["forward_log_error"] = str(e)
    return rec


@app.get("/api/forward_log")
def forward_log(symbol: str = SymbolQuery) -> dict:
    """Every recommendation recorded before its outcome existed, scored
    against what the index actually did next."""
    try:
        return forward_report(symbol)
    except Exception as e:
        raise HTTPException(503, f"Forward log failed: {e}")


@app.get("/api/intraday/research")
def intraday_research() -> dict:
    """What the 15-minute archive says about the system's own execution
    assumption: whether the opening print is a price you can get, and
    whether any fixed entry time beats it. Saved by
    scripts/intraday_research.py; these studies add no new hypotheses."""
    r = load_intraday_research()
    if r is None:
        raise HTTPException(503, "Intraday research has not been run yet — python scripts/intraday_research.py")
    return r


@app.get("/api/iv")
def implied_volatility() -> dict:
    """What options are pricing in: 30-day at-the-money implied volatility
    from NSE closing prices, where it stands against the past year, how it
    compares with India VIX, and the result of the one pre-registered test
    of using it as a filter. Saved by scripts/iv_research.py."""
    r = load_iv_research()
    if r is None:
        raise HTTPException(503, "Implied volatility not computed yet — python scripts/iv_research.py")
    s = load_iv_series().dropna(subset=["iv_30d"]).tail(260)
    year = s["iv_30d"] * 100
    return {
        "latest": r["series"]["latest"],
        # Computed here, not in the browser: every number the dashboard shows
        # comes from Python (I2).
        "last_year_stats": {"median": round(float(year.median()), 2), "low": round(float(year.min()), 2),
                            "high": round(float(year.max()), 2), "days": int(len(year))},
        "vix_check": r["vix_check"],
        "test": {k: r["preregistered_test"][k] for k in ("hypothesis", "registered", "verdict", "detail")},
        "last_year": [{"date": d, "iv_30d_pct": round(v * 100, 2),
                       "percentile": None if p != p else round(p)} for d, v, p in
                      zip(s.index, s["iv_30d"], s["iv_pct"])],
        "method_note": r["method_note"],
    }


class JournalEntry(BaseModel):
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    decision: Literal["TOOK", "SKIPPED", "WAITED"]
    underlying: Literal["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY"] | None = None
    option_type: Literal["CE", "PE"] | None = None
    strike: float | None = Field(default=None, gt=0)
    expiry: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    quantity: int | None = Field(default=None, gt=0, le=100000)
    entry_premium: float | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


class JournalClose(BaseModel):
    exit_premium: float = Field(ge=0)
    exit_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def _previous_close() -> float | None:
    """The last *final* daily close, which today's live price is measured
    against. During a session that is yesterday; after it, today."""
    from backtest.strategies import load_daily_data
    from market_data.live_quote import market_status as _status
    df, _ = load_daily_data("^NSEI", 260)
    try:
        open_now = bool(_status().get("is_open"))
    except Exception:
        open_now = False
    closes = df["close"].tolist()
    today = str(df.index[-1].date()) == datetime.now(kite_session.IST).date().isoformat()
    if open_now and today and len(closes) > 1:
        return float(closes[-2])
    return float(closes[-1])


@app.get("/api/access/check")
def access_check(request: Request) -> dict:
    """Does this caller already have what it needs? The phone asks this
    before anything else, so an unpaired device gets a clear answer rather
    than a wall of failed fetches."""
    return {"local": access.is_local(request), "token_required": not access.is_local(request),
            "paired": access.is_local(request) or bool(request.headers.get(access.HEADER))}


@app.get("/api/access/pairing")
def access_pairing(request: Request) -> dict:
    """The pairing link, for the QR code on the Mac's screen.

    Refused unless the caller is this Mac: the token is the whole lock, so it
    is shown on the machine that owns it and nowhere else. It is never
    logged, and never returned to a remote caller even with a valid token."""
    if not access.is_local(request):
        raise HTTPException(403, "Pairing can only be started on the Mac itself.")
    value = access.ensure_token()
    hosts = [h.strip() for h in (access._env("DASHBOARD_HOSTS") or "").split(",") if h.strip()]
    return {
        "token": value,
        "hosts": hosts,
        "links": [f"http://{h}:3000/?token={value}" for h in hosts],
        "note": ("Scan this on the phone once. The dashboard stores the token in that browser and sends it "
                 "with every request. Anyone holding this link can read your journal and paper book, so treat "
                 "it like a password: it is not shown anywhere else, and re-pairing replaces it."),
        "exposed": bool(hosts),
    }


@app.post("/api/access/rotate")
def access_rotate(request: Request) -> dict:
    """Forget the old token — every paired device stops working."""
    if not access.is_local(request):
        raise HTTPException(403, "Only the Mac can do this.")
    lines = [ln for ln in access.ENV_PATH.read_text().splitlines() if not ln.startswith(f"{access.TOKEN_KEY}=")]
    access.ENV_PATH.write_text("\n".join(lines) + "\n")
    access.ENV_PATH.chmod(0o600)
    access.ensure_token()
    return {"ok": True, "note": "Old devices are locked out. Pair them again from the Mac."}


# A live price older than this is shown as stale — NSE's feed caches for 15s,
# so anything past it is a refresh that did not happen.
LIVE_STALE_AFTER_S = 15


def _last_close() -> tuple[str, float]:
    """The newest final daily close and its date: what the header shows,
    labelled, when neither live source answers."""
    from backtest.strategies import load_daily_data
    df, _ = load_daily_data("^NSEI", 260)
    if "provisional" in df.columns:
        df = df[~df["provisional"].astype(bool)]
    return str(df.index[-1].date()), float(df["close"].iloc[-1])


@app.get("/api/live/tick")
def live_tick() -> dict:
    """The small, fast payload the dashboard polls while the market is open:
    the index now, and every open paper position marked at its live premium.
    Kite when logged in (one call, cached a second), NSE's public feed
    otherwise, and last close when neither answers — always labelled.

    Every cache read here is `stale_ok`: this endpoint is polled every two
    seconds by every open dashboard, and it must answer now. One thread
    refreshes while the rest are handed the last value. Waiting in a queue
    for a fresher number is how this endpoint once hung for good — NSE
    started throttling, a producer stopped returning, and every later poll
    piled up behind the lock it was holding."""
    from briefing.paper import live_marks

    now = datetime.now(kite_session.IST)
    out: dict = {"as_of": now.isoformat()}
    try:
        status = cached("market_status", ttl_seconds=60, producer=market_status, stale_ok=True)
    except Exception:
        # Unknown is not closed: saying "Closed" here once hid a live session
        # behind a 60-second poll. The clock's guess rides alongside, labelled.
        status = {"is_open": None, "status": "unknown"}
    out["market"] = {**status, "open_by_clock": open_by_clock(now)}

    try:
        marks = cached("live_marks", ttl_seconds=2, producer=live_marks, stale_ok=True)
    except Exception as e:
        marks = {"error": str(e)[:120], "index": None, "marks": {}, "source": None}
    out.update({k: marks.get(k) for k in ("index", "marks", "source", "paper", "quote_at")})

    # The change is computed here, not in the browser: every number on the
    # page comes from Python (I2).
    if out.get("index") is not None and out.get("change") is None:
        try:
            prev = cached("prev_close", ttl_seconds=600, producer=_previous_close, stale_ok=True)
            if prev:
                out["previous_close"] = prev
                out["change"] = round(out["index"] - prev, 2)
                out["change_pct"] = round((out["index"] / prev - 1) * 100, 2)
        except Exception:
            pass

    if out.get("index") is None:
        try:
            q = live_index_quote()
            out.update(index=q["last"], change=q.get("change"), change_pct=q.get("change_pct"),
                       source=q.get("source"), quote_at=q.get("fetched_at"))
            if q.get("age_s") is not None:
                out.update(age_s=q["age_s"], stale=bool(q.get("stale")))
        except Exception:
            pass

    if out.get("index") is None:
        # Neither live source answered: the last close, said to be exactly that.
        try:
            day, close = cached("last_close", ttl_seconds=600, producer=_last_close, stale_ok=True)
            out.update(index=close, source="last close", quote_at=f"{day}T15:30:00+05:30",
                       change=None, change_pct=None, stale=True)
        except Exception:
            out["source"] = "unavailable"

    # Every price carries its age. A number with no time on it is how a
    # frozen feed once passed for a live one.
    if out.get("quote_at") and "age_s" not in out:
        try:
            age = (now - datetime.fromisoformat(out["quote_at"])).total_seconds()
            out["age_s"] = round(max(age, 0.0), 1)
        except ValueError:
            pass
    out.setdefault("stale", out.get("age_s") is not None and out["age_s"] >= LIVE_STALE_AFTER_S)
    return out


@app.get("/api/paper")
def paper() -> dict:
    """Phase 14: hypothetical positions at real premiums, opened forward and
    never backfilled. Zero execution — nothing here reaches a broker."""
    from briefing.paper import report as paper_report
    return paper_report()


@app.get("/api/journal")
def journal() -> dict:
    """Phase 13: what you did, next to what the system said that session."""
    return journal_report()


class PaperFunds(BaseModel):
    amount: float = Field(gt=-10_000_000, lt=10_000_000)
    note: str | None = Field(default=None, max_length=200)


@app.post("/api/paper/funds")
def paper_funds(body: PaperFunds) -> dict:
    """Allocate (or withdraw) money the paper book may use. Paper only — no
    account is touched and nothing is ordered."""
    from storage import paper_db

    if body.amount == 0:
        raise HTTPException(422, "Amount must not be zero.")
    balance = paper_db.add_funds(body.amount, body.note)
    return {"allocated_rs": balance}


@app.post("/api/journal")
def journal_add(entry: JournalEntry) -> dict:
    if entry.decision == "TOOK" and not all([entry.underlying, entry.option_type, entry.strike, entry.expiry,
                                             entry.quantity, entry.entry_premium]):
        raise HTTPException(422, "A trade you took needs the index, CE/PE, strike, expiry, quantity and entry premium.")
    # The system's verdict is looked up, never typed: the comparison is only
    # honest if the user cannot restate what the system said.
    entry_id = journal_db.add({**entry.model_dump(), "system_action": system_action_for(entry.trade_date)})
    return {"id": entry_id}


@app.post("/api/journal/{entry_id}/close")
def journal_close(entry_id: int, body: JournalClose) -> dict:
    if not journal_db.close(entry_id, body.exit_premium, body.exit_date):
        raise HTTPException(404, "No open trade with that id.")
    return {"ok": True}


@app.delete("/api/journal/{entry_id}")
def journal_delete(entry_id: int) -> dict:
    if not journal_db.delete(entry_id):
        raise HTTPException(404, "No journal entry with that id.")
    return {"ok": True}


@app.get("/api/news")
def news(limit: int = 12, refresh_feeds: bool = True) -> dict:
    """What is being reported, split by when it arrived relative to the
    session an option buyer can act in.

    Not a signal. Jev says whether each headline is the kind of event that
    moves an index and which way it would push; that is a description of the
    news, and whether it predicts a return is a separate study.

    The feed pull is cached: several open dashboards must not multiply into
    a request per tab at every publisher on the list.
    """
    from news.feed import refresh as news_refresh
    from news.feed import view as news_view

    pulled = None
    if refresh_feeds:
        try:
            pulled = cached("news_refresh", ttl_seconds=180,
                            producer=lambda: news_refresh(), stale_ok=True)
        except Exception as e:
            pulled = {"error": str(e)[:160]}
    try:
        out = news_view(limit=limit)
    except Exception as e:
        raise HTTPException(503, f"News unavailable: {e}")
    return {**out, "last_pull": pulled}


@app.get("/api/news/research")
def news_research() -> dict:
    """The pre-registered news-tone hypotheses and their verdicts.

    Backtestable because GDELT gives away a daily tone series to 2018; the
    headline archive beside it can only run forward. Stored output, not a
    live recomputation."""
    from backtest.news_research import load_news_research

    out = load_news_research()
    if out is None:
        raise HTTPException(503, "News research has not been run yet "
                                 "(api/scripts/backfill_news_tone.py, then news_research.py).")
    return out


@app.get("/api/strategy_fit")
def strategy_fit() -> dict:
    """Which strategies today's market suits: whether each is forming (Python,
    on real prices) beside Jev's reading of whether today's conditions are the
    kind its premise was written for. A description, not a signal — it
    reaches neither the recommendation nor the paper book. Jev is asked at
    most every fifteen minutes, and only when the market picture changed."""
    from market_engine.strategy_fit import reading
    try:
        return cached("strategy_fit", ttl_seconds=60, producer=reading, stale_ok=True)
    except Exception as e:
        raise HTTPException(503, f"Strategy fit unavailable: {e}")


@app.get("/api/gift-nifty")
def gift_nifty() -> dict:
    """GIFT Nifty — NIFTY futures trading in GIFT City while India is shut.
    Context about the evening, not a signal: an option bought at the close
    cannot act on it before the next open."""
    from market_data.gift_nifty import fetch as fetch_gift
    from storage.gift_nifty_db import count as gift_snapshots
    try:
        q = cached("gift_nifty", ttl_seconds=60, producer=fetch_gift)
    except Exception as e:
        raise HTTPException(503, f"GIFT Nifty unavailable: {e}")
    if q is None:
        raise HTTPException(503, "GIFT Nifty: no traded near-month contract right now.")
    return {**q, "snapshots_archived": gift_snapshots(),
            "note": ("USD-settled NIFTY futures on NSE IX, trading about 21 hours a day. Its change is against its "
                     "own previous close. A future trades at a premium to the index, so its level is not NIFTY's "
                     "level. Context about the evening — not a forecast, and not something an option bought at "
                     "the close can act on. History is being recorded nightly from 22 Sep 2026; NSE IX publishes "
                     "no free archive.")}


@app.get("/api/replication")
def replication() -> dict:
    """Every judged pattern and three structural tests, re-run with their
    fixed setups on BANKNIFTY, SENSEX and Midcap Select alongside NIFTY,
    pooled by entry date. Saved by scripts/replication.py."""
    from backtest.replication import load_replication
    r = load_replication()
    if r is None:
        raise HTTPException(503, "Replication not run yet — python scripts/replication.py")
    return {k: r[k] for k in ("computed_at", "prereg_hash", "tests_counted", "coverage", "hypotheses")} | {
        "registered": r["preregistered"]["registered"], "measure": r["preregistered"]["measure"],
        "unit": r["preregistered"]["unit"]}


@app.get("/api/structural")
def structural() -> dict:
    """Six pre-registered ideas about market structure — volatility pricing,
    positioning, the calendar, opening gaps — each tested as a bought call or
    put on 2024-26 option prices it never saw. Saved by
    scripts/structural_research.py."""
    r = load_structural_research()
    if r is None:
        raise HTTPException(503, "Structural research not run yet — python scripts/structural_research.py")
    keep = ("name", "label", "family", "signal", "why", "hold_sessions", "signals_per_year", "status", "reason",
            "required_t", "development", "holdout")
    return {"computed_at": r["computed_at"], "period": r["period"], "registered": r["preregistered"]["registered"],
            "trade": r["preregistered"]["trade"], "tests_in_family": r["tests_in_family"],
            "hypotheses": [{k: h[k] for k in keep} for h in r["hypotheses"]],
            "overnight_vs_intraday": r["descriptions"]["overnight_vs_intraday"]}


@app.get("/api/market")
def market() -> dict:
    """The market context engine: why the latest session moved, what options
    cost against what the index has delivered, expiry-day flags, unusual
    strike activity and who is positioned how — plus the historical studies
    and the sourced principles behind them. For understanding; not a signal."""
    try:
        today = cached("market_today", ttl_seconds=1800, producer=market_today)
    except Exception as e:
        raise HTTPException(503, f"Market context failed: {e}")
    return {"today": today, "studies": load_market_studies(), "knowledge": KNOWLEDGE}


@app.get("/api/bars/archive")
def bars_archive() -> dict:
    """What's in the local index-bar archive (filled by scripts/backfill_bars.py)."""
    return {"series": archive_summary()}


@app.get("/api/zerodha/status")
def zerodha_status() -> dict:
    """Whether today has a Kite session, and the record of which days did.
    Zerodha requires a human login once a day; the days without one are the
    days 15-minute bars and live tracking are missing."""
    status = kite_session.session_status()
    if status["logged_in"]:
        login_log_db.record("LOGGED_IN", issued_at=status.get("issued_at"), user_id=status.get("user_id"))
    # The broker user ID stays in the local log. It used to be returned here —
    # to a paired phone over plain HTTP too — and nothing on screen uses it.
    history = login_log_db.summary()
    history = {**history, "recent": [{k: v for k, v in r.items() if k != "user_id"}
                                     for r in history.get("recent", [])]}
    return {**{k: v for k, v in status.items() if k != "user_id"}, "history": history}


@app.get("/api/zerodha/login")
def zerodha_login() -> RedirectResponse:
    try:
        return RedirectResponse(kite_session.login_url())
    except kite_session.KiteNotConfigured as e:
        raise HTTPException(503, str(e))


@app.get("/api/zerodha/callback")
def zerodha_callback(request_token: str | None = None, status: str | None = None) -> RedirectResponse:
    """Kite redirects here after the user logs in on zerodha.com."""
    if status != "success" or not request_token:
        raise HTTPException(400, f"Kite login did not succeed (status={status}).")
    try:
        done = kite_session.complete_login(request_token)
        login_log_db.record("LOGGED_IN", issued_at=done["issued_at"], user_id=done.get("user_id"),
                            note="logged in through Kite")
    except kite_session.KiteNotConfigured as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"Token exchange with Kite failed: {e}")
    return RedirectResponse("http://localhost:3000/?zerodha=connected")


def _pattern_options() -> dict:
    research = load_research()
    if research is None:
        raise HTTPException(503, "Pattern-option research not computed yet — run: python scripts/pattern_options.py")
    # The implied-volatility description of each pattern's trades, where it
    # has been computed. Description only: which IV its options were bought at.
    iv = (load_iv_research() or {}).get("by_pattern", {})
    return {**research, "patterns": [{**p, "iv": iv.get(p["strategy"])} for p in research["patterns"]]}


@app.get("/api/patterns/options")
def patterns_options() -> dict:
    """Every pattern ranked by what its suggested option actually made on
    real NSE premiums, judged only on data the choice never saw."""
    return _pattern_options()


@app.get("/api/patterns/today")
def patterns_today(symbol: str = SymbolQuery) -> dict:
    """Patterns that formed on the last close or could form on the next one,
    each with the option it points to and that option's track record."""
    try:
        prox = cached(f"proximity:{symbol}", ttl_seconds=1800, producer=lambda: pattern_proximity(symbol))
    except Exception as e:
        raise HTTPException(503, f"Pattern proximity failed: {e}")
    try:
        research = {p["strategy"]: p for p in _pattern_options()["patterns"]}
        computed_at = _pattern_options()["computed_at"]
    except HTTPException:
        research, computed_at = {}, None

    keep = ("suggested_option", "holdout", "baseline", "holdout_t_stat", "holdout_ci_95", "edge_over_no_signal_ci_95", "status", "reason", "forms_per_year")
    patterns = [{**p, **{k: research.get(p["strategy"], {}).get(k) for k in keep}} for p in prox["patterns"]]
    return {**prox, "patterns": patterns, "option_research_computed_at": computed_at}


@app.get("/api/live/patterns")
def live_patterns_endpoint(symbol: str = SymbolQuery) -> dict:
    """Phase 10: during market hours, which patterns would form if today
    closed at the current level — provisional until 15:30."""
    try:
        live = cached("live_patterns", ttl_seconds=60, producer=live_patterns)
        prox = cached(f"proximity:{symbol}", ttl_seconds=1800, producer=lambda: pattern_proximity(symbol))
    except Exception as e:
        raise HTTPException(503, f"Live pattern tracking failed: {e}")
    return {**live, "patterns": merge_live(live, prox, load_research())}


@app.get("/api/similarity")
def similarity(symbol: str = SymbolQuery) -> dict:
    """Phase 11: past days most like today and what followed, next to the
    base rate and a walk-forward test of whether analogs predict anything."""
    try:
        return cached(f"similarity:{symbol}", ttl_seconds=1800, producer=lambda: run_similarity(symbol))
    except Exception as e:
        raise HTTPException(503, f"Similarity failed: {e}")


class CopilotQuestion(BaseModel):
    # The card caps it at 1,000; so does the API, since every question costs
    # a model call and the guards' calls.
    question: str = Field(max_length=1000)


def _live_or_none() -> dict | None:
    try:
        live = cached("live_patterns", ttl_seconds=60, producer=live_patterns)
        prox = cached("proximity:^NSEI", ttl_seconds=1800, producer=lambda: pattern_proximity("^NSEI"))
        return {**live, "patterns": merge_live(live, prox, load_research())}
    except Exception:
        return None


def _copilot_call(fn):
    try:
        return fn()
    except LLMNotConfigured as e:
        raise HTTPException(503, str(e))
    except LLMError as e:
        raise HTTPException(502, str(e))


@app.get("/api/copilot/status")
def copilot_status() -> dict:
    cfg = llm_config()
    return {"configured": cfg["has_key"], "provider": cfg["provider"], "model": cfg["model"],
            "guards": {"numbers": True, "forecast": jev_available(), "claims": jev_available(), "routing": jev_available()}}


@app.get("/api/copilot/composed")
def copilot_composed() -> dict:
    """The daily explanation as Python composes it, with no model involved.
    Runs beside the model's version every day and is graded by the same
    judge; it is what gets served if the provider is down."""
    from copilot.context import build_context
    return copilot.composed_explanation(build_context(scope="today"))


@app.get("/api/copilot/record")
def copilot_record() -> dict:
    """What the guards have actually done: how many answers were shown,
    withheld and why, and how the two grades are trending. Withheld answers
    are listed because each is a candidate case for scripts/check_guards.py."""
    return copilot_record_summary()


@app.get("/api/copilot/explain")
def copilot_explain() -> dict:
    """Phase 12: today's dashboard in plain language. Saved once per trading
    day. Any number not found in the computed data gets the answer withheld."""
    return _copilot_call(copilot.explain_today)


@app.post("/api/copilot/ask")
def copilot_ask(body: CopilotQuestion) -> dict:
    if not body.question.strip():
        raise HTTPException(400, "Empty question.")
    return _copilot_call(lambda: copilot.ask(body.question, live=_live_or_none()))
