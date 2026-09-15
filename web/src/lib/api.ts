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

export interface BacktestMetrics {
  num_trades: number;
  win_rate?: number;
  avg_win_pct?: number;
  avg_loss_pct?: number;
  expectancy_pct?: number;
  profit_factor?: number | null;
  max_drawdown_pct?: number;
  sharpe_ratio_approx?: number | null;
  sortino_ratio_approx?: number | null;
  avg_holding_days?: number;
  sample_size_warning?: string | null;
  note?: string;
}

export interface BacktestResult {
  strategy: string;
  params: Record<string, number>;
  symbol: string;
  period: { start: string; end: string; bars: number };
  metrics: BacktestMetrics;
}

// No mock fallback here on purpose: a fake backtest result would be exactly
// the kind of invented statistic this project is built to avoid. If the API
// is unreachable, the UI shows "not available," not a plausible-looking lie.
export async function fetchBacktest(days = 7000): Promise<ApiResult<BacktestResult | null>> {
  try {
    const res = await fetch(`${API_BASE}/api/backtest/ema_pullback?days=${days}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: await res.json(), live: true };
  } catch {
    return { data: null, live: false };
  }
}

export interface ResearchCompareResult {
  symbol: string;
  period: { start: string; end: string; bars: number };
  hold_days: number;
  results: Record<string, BacktestMetrics>;
  total_hypotheses_tested_all_time: number;
}

export async function fetchResearchCompare(days = 7000): Promise<ApiResult<ResearchCompareResult | null>> {
  try {
    const res = await fetch(`${API_BASE}/api/research/compare?days=${days}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: await res.json(), live: true };
  } catch {
    return { data: null, live: false };
  }
}

export interface ParamSweepCell {
  ema_span: number;
  hold_days: number;
  num_trades: number;
  expectancy_pct: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
}

export interface ParamSweepResult {
  symbol: string;
  period: { start: string; end: string; bars: number };
  grid: ParamSweepCell[];
  combinations_tested: number;
  combinations_with_positive_expectancy: number;
  total_hypotheses_tested_all_time: number;
}

export async function fetchParamSweep(days = 7000): Promise<ApiResult<ParamSweepResult | null>> {
  try {
    const res = await fetch(`${API_BASE}/api/research/param_sweep?days=${days}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: await res.json(), live: true };
  } catch {
    return { data: null, live: false };
  }
}

export interface WalkForwardFold {
  period: { start: string; end: string };
  metrics: BacktestMetrics;
}

export interface ValidationResult {
  strategy: string;
  final_status: "APPROVED" | "CONDITIONAL" | "REJECTED";
  final_reason: string;
  walk_forward: {
    period: { start: string; end: string };
    n_folds: number;
    folds: WalkForwardFold[];
    folds_with_positive_expectancy: number;
    folds_with_any_trades: number;
  };
  holdout: {
    split_date: string;
    development: { period: { start: string; end: string }; metrics: BacktestMetrics };
    holdout: { period: { start: string; end: string }; metrics: BacktestMetrics };
    status: string;
    reason: string;
  };
  methodology_note: string;
}

export async function fetchValidation(days = 7000): Promise<ApiResult<ValidationResult | null>> {
  try {
    const res = await fetch(`${API_BASE}/api/validation/ema_pullback?days=${days}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: await res.json(), live: true };
  } catch {
    return { data: null, live: false };
  }
}
