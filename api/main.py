from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="NIFTY Copilot API")

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


@app.get("/api/snapshot", response_model=Snapshot)
def get_snapshot() -> Snapshot:
    # Placeholder — identical shape to web/src/lib/mock-data.ts.
    # Real values arrive in Phase 4 once a market-data provider is wired in.
    return Snapshot(
        symbol="NIFTY 50",
        price=24812.35,
        change=104.2,
        change_pct=0.42,
        as_of="15:15 IST candle close",
        provisional=False,
        regime="TREND_BULL",
    )


@app.get("/api/indicators", response_model=list[Indicator])
def get_indicators() -> list[Indicator]:
    return [
        Indicator(name="EMA 20 vs EMA 50", value="EMA20 above EMA50", read="supports"),
        Indicator(name="VWAP", value="Price 0.3% above VWAP", read="supports"),
        Indicator(name="RSI (14)", value="58", read="neutral"),
        Indicator(name="ADX (14)", value="27 (trending)", read="supports"),
        Indicator(name="ATR (14)", value="142 pts", read="neutral"),
        Indicator(name="Relative Volume", value="1.3x 20-day average", read="supports"),
        Indicator(name="India VIX", value="13.1", read="neutral"),
    ]
