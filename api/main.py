from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backtest import run_ema_pullback_backtest
from backtest.research import run_all_strategies, run_ema_pullback_param_sweep
from backtest.options_research import run_options_strike_sweep
from cache import cached
from backtest.walkforward import evaluate_strategy
from briefing import build_briefing, build_recommendation
from options.advisor import translate_to_options
from options.chain_analytics import live_chain_analytics
from storage import archive_stats, record_strategy_evaluation, strategy_history, strategy_playbook
from market_data import Candle, CSVProvider, YFinanceProvider, ZerodhaProvider
from market_data import kite_session
from market_data.bar_archive import ArchiveProvider, archive_summary
from market_data.live_quote import live_index_quote, market_status
from quant import build_analysis

app = FastAPI(title="NIFTY Copilot API")

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
    allow_methods=["GET"],
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
    symbol: str = Query("^NSEI"),
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


@app.get("/api/backtest/ema_pullback")
def backtest_ema_pullback(
    symbol: str = Query("^NSEI"),
    days: int = Query(7000, ge=100, le=10000, description="Free Yahoo Finance daily data goes back to 2007-09-17 for NIFTY (~7000 days)"),
    hold_days: int = Query(10, ge=1, le=60),
) -> dict:
    """Runs the EMA-pullback example strategy over real historical NIFTY
    data and returns every metric the project plan asked for — expectancy,
    profit factor, drawdown, Sharpe/Sortino, and breakdowns by year and by
    regime. This is Phase 6 (prove the engine works), not Phase 8
    (walk-forward validation) — treat results as exploratory."""
    try:
        return run_ema_pullback_backtest(symbol=symbol, days=days, hold_days=hold_days)
    except Exception as e:
        raise HTTPException(503, f"Backtest failed: {e}")


@app.get("/api/research/compare")
def research_compare(
    symbol: str = Query("^NSEI"),
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


@app.get("/api/research/param_sweep")
def research_param_sweep(
    symbol: str = Query("^NSEI"),
    days: int = Query(7000, ge=100, le=10000),
) -> dict:
    """Parameter-robustness check for the EMA Pullback strategy: sweeps
    ema_span and hold_days across nearby values. A strategy that only
    "works" at one exact setting and collapses one step either side is a
    sign of overfitting, not a real effect."""
    try:
        return run_ema_pullback_param_sweep(symbol=symbol, days=days)
    except Exception as e:
        raise HTTPException(503, f"Parameter sweep failed: {e}")


@app.get("/api/validation/{strategy_name}")
def validate_strategy(
    strategy_name: str,
    symbol: str = Query("^NSEI"),
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


@app.get("/api/options/advisor")
def options_advisor(
    symbol: str = Query("^NSEI"),
    hold_days: int = Query(10, ge=1, le=60),
) -> dict:
    """Translates today's EMA Pullback signal (the only strategy with any
    real edge, still CONDITIONAL not APPROVED) into options guidance --
    strike/expiry heuristics only. No live premiums, IV, or Greeks: that
    data isn't in this system, and inventing plausible numbers for it
    would be exactly the kind of fabricated statistic this project exists
    to avoid."""
    try:
        return translate_to_options(symbol=symbol, hold_days=hold_days)
    except Exception as e:
        raise HTTPException(503, f"Options advisor failed: {e}")


@app.get("/api/briefing")
def research_briefing(
    symbol: str = Query("^NSEI"),
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


@app.get("/api/options/strike_sweep")
def options_strike_sweep(
    symbol: str = Query("^NSEI"),
    days: int = Query(3000, ge=200, le=10000),
    hold_days: int = Query(10, ge=1, le=60),
) -> dict:
    """Sweeps strike offset against expiry distance to measure which
    contract choice actually performed best when the signal fired —
    returns are on PREMIUM, including theta decay and modeled costs.
    Reports how many combinations were tested alongside the results.

    Cached briefly: each grid cell is a full backtest against the options
    archive, too slow to recompute per page load, but short enough a TTL
    that results refresh as the archive backfills."""
    try:
        return cached(
            f"strike_sweep:{symbol}:{days}:{hold_days}",
            ttl_seconds=900,
            producer=lambda: run_options_strike_sweep(
                symbol=symbol, days=days, hold_days=hold_days
            ),
        )
    except Exception as e:
        raise HTTPException(503, f"Strike sweep failed: {e}")


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
def recommendation(symbol: str = Query("^NSEI")) -> dict:
    """Today's call, put, or no-trade verdict across every tested strategy
    in both directions. Will say NO_TRADE unless a signal clears a real
    expectancy and sample-size bar — that is the intended behaviour."""
    try:
        return cached(
            f"recommendation:{symbol}",
            ttl_seconds=600,
            producer=lambda: build_recommendation(symbol=symbol),
        )
    except Exception as e:
        raise HTTPException(503, f"Recommendation failed: {e}")


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
