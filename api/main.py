from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backtest.research import run_all_strategies
from cache import cached
from backtest.walkforward import evaluate_strategy
from backtest.intraday import load_research as load_intraday_research
from backtest.iv_research import load_iv_research, load_series as load_iv_series
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
from market_data.live_quote import live_index_quote, market_status
from quant import build_analysis

app = FastAPI(title="NIFTY Copilot API")

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
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
    try:
        return run_all_strategies(symbol=symbol, days=days, hold_days=hold_days)
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
    symbol: str = Query("NIFTY"),
    expiry: str | None = Query(None, description="e.g. 22-Sep-2026; defaults to nearest"),
) -> dict:
    """Live NIFTY option chain analytics from NSE — PCR, open-interest
    concentrations, ATM implied volatility. Measurements, not signals:
    none of these have been backtested on NIFTY yet."""
    try:
        return live_chain_analytics(symbol=symbol, expiry=expiry)
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
    return kite_session.session_status()


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
        kite_session.complete_login(request_token)
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

    keep = ("suggested_option", "holdout", "baseline", "holdout_t_stat", "status", "reason", "forms_per_year")
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
    question: str


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
    return copilot.composed_explanation(build_context())


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
