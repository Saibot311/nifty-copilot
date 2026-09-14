from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
