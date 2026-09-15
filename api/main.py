from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backtest import run_ema_pullback_backtest
from backtest.research import run_all_strategies, run_ema_pullback_param_sweep
from backtest.walkforward import evaluate_strategy
from options.advisor import translate_to_options
from market_data import Candle, CSVProvider, YFinanceProvider
from quant import build_analysis

app = FastAPI(title="NIFTY Copilot API")

SAMPLE_CSV = Path(__file__).parent / "market_data" / "sample_data" / "nifty_synthetic_15m.csv"

PROVIDERS = {
    "csv": CSVProvider(SAMPLE_CSV),
    "yfinance": YFinanceProvider(),
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
    provider: str = Query("yfinance", description="csv | yfinance"),
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
    candles: list[Candle] = PROVIDERS[provider].get_ohlc(symbol, timeframe, start, end)

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


@app.get("/api/validation/ema_pullback")
def validate_ema_pullback(
    symbol: str = Query("^NSEI"),
    days: int = Query(7000, ge=100, le=10000),
    hold_days: int = Query(10, ge=1, le=60),
    n_folds: int = Query(5, ge=2, le=10),
    train_frac: float = Query(0.7, gt=0.3, lt=0.95),
) -> dict:
    """Phase 8: walk-forward folds + a development/holdout split, combined
    into one honest APPROVED / CONDITIONAL / REJECTED verdict. Deliberately
    stricter than either check alone — see the methodology_note in the
    response for the real limitation in what this can and can't prove."""
    try:
        return evaluate_strategy(
            symbol=symbol, days=days, hold_days=hold_days, n_folds=n_folds, train_frac=train_frac
        )
    except Exception as e:
        raise HTTPException(503, f"Validation run failed: {e}")


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
