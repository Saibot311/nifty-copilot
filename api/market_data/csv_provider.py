import csv
from datetime import date, datetime
from pathlib import Path

from .base import Candle


class CSVProvider:
    """Reads OHLC candles from a local CSV file. Ignores `symbol` — a CSV
    file is already one specific instrument. Used for offline testing and
    as a stand-in for any future vendor that only hands you a file export
    (which is exactly what most paid Indian data vendors do anyway)."""

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> list[Candle]:
        candles = []
        with open(self.csv_path, newline="") as f:
            reader = csv.DictReader(row for row in f if not row.startswith("#"))
            for row in reader:
                ts = datetime.fromisoformat(row["timestamp"])
                if not (start <= ts.date() <= end):
                    continue
                candles.append(
                    Candle(
                        timestamp=row["timestamp"],
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]) if row.get("volume") else None,
                    )
                )
        return candles
