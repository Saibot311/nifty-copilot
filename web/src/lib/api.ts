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
export async function get<T>(path: string): Promise<ApiResult<T>> {
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

export interface ResearchCompareResult {
  symbol: string;
  period: { start: string; end: string; bars: number };
  hold_days: number;
  results: Record<string, BacktestMetrics>;
  buy_and_hold_baseline?: { num_trades: number; expectancy_pct: number | null; profit_factor: number | null };
  always_short_baseline?: { num_trades: number; expectancy_pct: number | null; profit_factor: number | null };
  baseline_note?: string;
  total_hypotheses_tested_all_time: number;
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
  live_option_chain?: LiveChain;
  how_to_read_this: string;
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
  direction: "long" | "short";
  option_type: "CE" | "PE";
  status: Verdict;
  verdict_reason: string | null;
  suggested_option: string | null;
  holdout_trades: number;
  holdout_avg_profit_per_lot_rs: number | null;
  holdout_t_stat: number | null;
  qualifies: boolean;
  why_not: string | null;
}

export interface EvidenceBar {
  min_t: number;
  patterns_judged: number;
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

export interface ForwardOutcome {
  index_move_pct: number;
  trade_return_pct: number | null;
}

export interface ForwardEntry {
  as_of: string;
  recorded_at: string;
  action: Recommendation["action"];
  regime: string;
  close_as_of: number;
  headline: string;
  entry_date?: string;
  entry_open?: number;
  outcomes: Partial<Record<"1d" | "5d" | "10d", ForwardOutcome>>;
}

export interface ForwardLog {
  entries: ForwardEntry[];
  summary: {
    days_logged: number;
    logging_since: string | null;
    by_action: Record<Recommendation["action"], number>;
    completed_trades_10d: number;
    hit_rate_10d: number | null;
    avg_return_10d_pct: number | null;
  };
  note: string;
}

export const fetchForwardLog = () => get<ForwardLog>("/api/forward_log");
export const fetchLiveQuote = () => get<LiveQuote>("/api/live");
export const fetchRecommendation = () => get<Recommendation>("/api/recommendation");
export const fetchSnapshot = () => get<Snapshot>("/api/snapshot");
export const fetchIndicators = () => get<IndicatorReading[]>("/api/indicators");
export const fetchCandles = (days = 140) =>
  get<CandleResponse>(`/api/candles?provider=yfinance&days=${days}`);
export const fetchResearchCompare = (days = 7000) =>
  get<ResearchCompareResult>(`/api/research/compare?days=${days}`);
export const fetchBriefing = () => get<Briefing>("/api/briefing");

export type Verdict = "APPROVED" | "CONDITIONAL" | "REJECTED";

export interface SuggestedOption {
  type: "CE" | "PE";
  moneyness: string;
  moneyness_pct: number;
  min_days_to_expiry: number;
  hold_days: number;
  description: string;
}

export interface OptionPeriodStats {
  num_trades: number;
  win_rate?: number;
  avg_return_pct?: number;
  median_return_pct?: number;
  worst_return_pct?: number;
  best_return_pct?: number;
  avg_premium?: number;
  avg_profit_per_lot_rs?: number;
  total_profit_per_lot_rs?: number;
}

export interface PatternOptionResult {
  strategy: string;
  label: string;
  direction: "long" | "short";
  option_type: "CE" | "PE";
  forms_when?: string;
  why?: string;
  forms_per_year: number;
  forms_per_year_since_2018: number;
  configs_tested: number;
  suggested_option?: SuggestedOption;
  development?: OptionPeriodStats;
  holdout?: OptionPeriodStats;
  baseline?: {
    development_avg_return_pct: number;
    holdout_avg_return_pct: number;
    development_avg_profit_per_lot_rs: number;
    holdout_avg_profit_per_lot_rs: number;
  };
  holdout_t_stat?: number | null;
  status: Verdict;
  reason: string;
}

export interface PatternOptionsResearch {
  computed_at: string;
  options_period: { start: string; split: string; end: string };
  lot_size: number;
  configs_tested_total: number;
  patterns: PatternOptionResult[];
  method_note: string;
}

export interface PatternToday {
  strategy: string;
  label: string;
  direction: "long" | "short";
  option_type: "CE" | "PE";
  forms_when?: string;
  why?: string;
  formed_today: boolean | null;
  probability_next: number | null;
  trigger: {
    close_ranges_pct: [number, number][];
    close_ranges_level: [number, number][];
    partial_ranges_level: [number, number][];
    needs: string[];
  } | null;
  note?: string;
  suggested_option?: SuggestedOption | null;
  holdout?: OptionPeriodStats | null;
  baseline?: { holdout_avg_return_pct: number; holdout_avg_profit_per_lot_rs: number } | null;
  holdout_t_stat?: number | null;
  status?: Verdict | null;
  reason?: string | null;
  forms_per_year?: number | null;
}

export interface PatternsToday {
  as_of: string;
  last_close: number;
  patterns: PatternToday[];
  method_note: string;
  option_research_computed_at: string | null;
}

export const fetchPatternOptions = () => get<PatternOptionsResearch>("/api/patterns/options");
export const fetchPatternsToday = () => get<PatternsToday>("/api/patterns/today");

export interface LivePatternRow {
  strategy: string;
  label: string;
  option_type: "CE" | "PE";
  would_form_now: boolean;
  trigger_ranges_level: [number, number][];
  points_to_trigger: number | null;
  pct_to_trigger: number | null;
  status: Verdict | null;
  suggested_option: string | null;
  holdout: OptionPeriodStats | null;
  baseline_rs: number | null;
  holdout_t_stat: number | null;
}

export interface LivePatterns {
  market_open: boolean;
  message?: string;
  provisional?: boolean;
  as_of?: string;
  basis?: string;
  previous_close?: number;
  candle?: { open: number; high: number; low: number; close: number };
  change_pct?: number;
  note?: string;
  patterns: LivePatternRow[];
}

export const fetchLivePatterns = () => get<LivePatterns>("/api/live/patterns");

export interface SimilarityAnalog {
  date: string;
  distance: number;
  close: number;
  ret20: number;
  vs_ema50: number;
  rsi14: number;
  vol20: number;
  off_high: number;
  fwd_1d: number;
  fwd_5d: number;
  fwd_10d: number;
}

interface OutcomeStats {
  pct_higher: number;
  median_pct: number;
}

interface AnalogOptionSide {
  trades: number;
  win_rate: number | null;
  avg_profit_per_lot_rs: number | null;
}

export interface Similarity {
  as_of: string;
  today: Record<string, number>;
  feature_labels: Record<string, string>;
  analogs: SimilarityAnalog[];
  outcomes: { analogs: Record<"1d" | "5d" | "10d", OutcomeStats>; all_days: Record<"1d" | "5d" | "10d", OutcomeStats> };
  options_on_analog_days: { hold_days: number; option: string; CE: AnalogOptionSide; PE: AnalogOptionSide } | null;
  walk_forward: {
    test_points: number;
    period_start?: string;
    rank_correlation?: number;
    t_stat?: number;
    direction_hit_rate?: number;
    verdict: string;
  };
  method_note: string;
}

export const fetchSimilarity = () => get<Similarity>("/api/similarity");

export interface CopilotStatus {
  configured: boolean;
  provider: string;
  model: string | null;
  prediction_guard: boolean;
}

export interface CopilotAnswer {
  ok: boolean;
  answer: string | null;
  reason?: string;
  provider: string;
  model: string;
  as_of_close: string;
  cached?: boolean;
  prediction_check?: { checked: boolean; blocked: boolean; scores: Record<string, number>; reason: string };
}

export const fetchCopilotStatus = () => get<CopilotStatus>("/api/copilot/status");

/** Browser-side calls: these hit a rate-limited free tier, so only on click. */
export async function copilotRequest(path: string, question?: string): Promise<{ data?: CopilotAnswer; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, question
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) }
      : { cache: "no-store" });
    const body = await res.json();
    return res.ok ? { data: body as CopilotAnswer } : { error: body.detail ?? `HTTP ${res.status}` };
  } catch {
    return { error: "Backend not reachable." };
  }
}
