const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Regime = "TREND_BULL" | "TREND_BEAR" | "RANGE" | "TRANSITION";

export interface ApiResult<T> {
  data: T | null;
  live: boolean;
}

/** Every fetch returns null rather than substituted values when the API is
 *  unreachable. This project's core rule is that no displayed number is
 *  invented — a plausible-looking placeholder price would break that even
 *  with a warning banner attached. */
async function get<T>(path: string): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { data: (await res.json()) as T, live: true };
  } catch {
    return { data: null, live: false };
  }
}

export interface Snapshot {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  as_of: string;
  provisional: boolean;
  regime: Regime;
}

export interface IndicatorReading {
  name: string;
  value: string;
  read: "supports" | "conflicts" | "neutral";
}

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  provisional?: boolean;
}

export interface CandleResponse {
  provider: string;
  symbol: string;
  timeframe: string;
  count: number;
  candles: Candle[];
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
  label?: string;
  direction?: string;
  option_type?: "CE" | "PE";
  vs_baseline_pct?: number | null;
}

export interface BacktestResult {
  strategy: string;
  params: Record<string, number>;
  symbol: string;
  period: { start: string; end: string; bars: number };
  metrics: BacktestMetrics;
}

export interface ResearchCompareResult {
  symbol: string;
  period: { start: string; end: string; bars: number };
  hold_days: number;
  results: Record<string, BacktestMetrics>;
  buy_and_hold_baseline?: { num_trades: number; expectancy_pct: number | null; profit_factor: number | null };
  baseline_note?: string;
  total_hypotheses_tested_all_time: number;
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

export interface OptionsAdvice {
  as_of: string;
  actionable_today: boolean;
  message?: string;
  direction?: string;
  rationale?: string;
  strike_guidance?: string;
  expiry_guidance?: string;
  validation_status: string;
  critical_warnings?: string[];
  recent_signal_dates: string[];
}

export interface LiveChain {
  as_of?: string;
  underlying_value?: number;
  expiry?: string;
  atm_strike?: number;
  atm_iv?: { call: number | null; put: number | null };
  open_interest?: {
    total_call: number;
    total_put: number;
    pcr: number | null;
    max_call_oi_strike: number | null;
    max_put_oi_strike: number | null;
  };
  strikes_analysed?: number;
  interpretation_caveat?: string;
  unavailable?: string;
}

export interface Briefing {
  as_of: string;
  symbol: string;
  market_state: { price: number; change: number; change_pct: number; regime: Regime };
  evidence: {
    bullish: string[];
    bearish: string[];
    neutral_or_context: string[];
    net_read: string;
    counts: { bullish: number; bearish: number };
  };
  levels: { confirmation_would_be: string[]; invalidation_would_be: string[] };
  signal?: {
    strategy?: string;
    active_today?: boolean;
    recent_signal_dates?: string[];
    validation_status?: string;
    validation_reason?: string;
    unavailable?: string;
  };
  live_option_chain?: LiveChain;
  how_to_read_this: string;
}

export interface OptionsArchive {
  option_bars: number;
  trading_days_with_data: number;
  days_checked: number;
  first_date: string | null;
  last_date: string | null;
}

export interface StrikeSweepCell {
  strike_offset_pts: number;
  moneyness: string;
  min_days_to_expiry: number;
  num_trades: number;
  win_rate: number | null;
  expectancy_pct: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
  max_drawdown_full_reinvestment_pct?: number | null;
  sample_size_warning: string | null;
}

export interface StrikeSweepResult {
  strategy: string;
  signal_count: number;
  hold_days: number;
  grid: StrikeSweepCell[];
  combinations_tested: number;
  combinations_with_trades: number;
  combinations_with_positive_expectancy: number;
  best_cell: StrikeSweepCell | null;
  multiple_comparisons_note: string;
  cost_note: string;
  position_sizing_note?: string;
}

export interface LiveQuote {
  index: string;
  last: number;
  change: number;
  change_pct: number;
  open: number;
  high: number;
  low: number;
  previous_close: number;
  india_vix: number | null;
  india_vix_change_pct: number | null;
  market: { status: string | null; trade_date: string | null; is_open: boolean };
}

export interface RecommendationCandidate {
  strategy: string;
  label: string;
  direction: string;
  option_type: "CE" | "PE";
  index_expectancy_pct: number | null;
  index_trades: number;
  qualifies: boolean;
  why_not: string | null;
}

export interface EvidenceBar {
  min_expectancy_pct: number;
  min_trades: number;
  num_hypotheses_tested: number;
  scale_factor: number;
  methodology_note: string;
}

export interface Recommendation {
  as_of: string;
  regime: string;
  action: "NO_TRADE" | "CONSIDER_CALL" | "CONSIDER_PUT";
  headline: string;
  reason: string;
  candidates: RecommendationCandidate[];
  warnings: string[];
  evidence_bar?: EvidenceBar;
}

export interface PlaybookEntry {
  id: number;
  strategy: string;
  label: string;
  checked_at: string;
  status: "APPROVED" | "CONDITIONAL" | "REJECTED";
  reason: string;
  num_trades: number | null;
  expectancy_pct: number | null;
  profit_factor: number | null;
  folds_positive: number | null;
  folds_total: number | null;
}

export const fetchPlaybook = () => get<{ strategies: PlaybookEntry[] }>("/api/strategies/playbook");
export const fetchLiveQuote = () => get<LiveQuote>("/api/live");
export const fetchRecommendation = () => get<Recommendation>("/api/recommendation");
export const fetchSnapshot = () => get<Snapshot>("/api/snapshot");
export const fetchIndicators = () => get<IndicatorReading[]>("/api/indicators");
export const fetchCandles = (days = 140) =>
  get<CandleResponse>(`/api/candles?provider=yfinance&days=${days}`);
export const fetchBacktest = (days = 7000) =>
  get<BacktestResult>(`/api/backtest/ema_pullback?days=${days}`);
export const fetchResearchCompare = (days = 7000) =>
  get<ResearchCompareResult>(`/api/research/compare?days=${days}`);
export const fetchParamSweep = (days = 7000) =>
  get<ParamSweepResult>(`/api/research/param_sweep?days=${days}`);
export const fetchValidation = (days = 7000) =>
  get<ValidationResult>(`/api/validation/ema_pullback?days=${days}`);
export const fetchOptionsAdvisor = () => get<OptionsAdvice>("/api/options/advisor");
export const fetchBriefing = () => get<Briefing>("/api/briefing");
export const fetchOptionsArchive = () => get<OptionsArchive>("/api/options/archive");
export const fetchStrikeSweep = () => get<StrikeSweepResult>("/api/options/strike_sweep");
