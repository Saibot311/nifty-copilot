import { mockIndicators, mockSnapshot, type IndicatorReading } from "@/lib/mock-data";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Snapshot {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  as_of: string;
  provisional: boolean;
  regime: "TREND_BULL" | "TREND_BEAR" | "RANGE" | "TRANSITION";
}

export interface ApiResult<T> {
  data: T;
  live: boolean; // false = API was unreachable, showing local mock data instead
}

export async function fetchSnapshot(): Promise<ApiResult<Snapshot>> {
  try {
    const res = await fetch(`${API_BASE}/api/snapshot`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: await res.json(), live: true };
  } catch {
    return {
      data: {
        symbol: mockSnapshot.symbol,
        price: mockSnapshot.price,
        change: mockSnapshot.change,
        change_pct: mockSnapshot.changePct,
        as_of: mockSnapshot.asOf,
        provisional: mockSnapshot.provisional,
        regime: mockSnapshot.regime,
      },
      live: false,
    };
  }
}

export async function fetchIndicators(): Promise<ApiResult<IndicatorReading[]>> {
  try {
    const res = await fetch(`${API_BASE}/api/indicators`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: await res.json(), live: true };
  } catch {
    return { data: mockIndicators, live: false };
  }
}
