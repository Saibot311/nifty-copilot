/** Where the API is, from wherever this code is running.
 *
 *  On the Mac (server render, or a browser at localhost) that is localhost.
 *  On a phone, "localhost" would be the phone itself — so a browser on any
 *  other host talks to that same host on the API's port. One build works
 *  from the Mac and from a paired phone without being rebuilt per address. */
const CONFIGURED = process.env.NEXT_PUBLIC_API_URL;

function apiBase(): string {
  if (CONFIGURED) return CONFIGURED;
  if (typeof window === "undefined") return "http://localhost:8000";
  // The page's own host name, always: the API refuses requests a browser
  // marks cross-site, and to a browser 127.0.0.1 and localhost are different
  // sites, so a page at 127.0.0.1 calling localhost:8000 would be refused.
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:8000`;
}

const TOKEN_KEY = "copilot_token";

/** The pairing token now lives in an HttpOnly cookie that page scripts
 *  cannot read: the dashboard server sets it from the pairing link and sends
 *  the phone on without the token in its URL, and every API call carries it
 *  (`credentials: "include"`). A phone paired before that kept a copy in
 *  localStorage; it is still sent as a header until the API confirms the
 *  cookie works, and then deleted (forgetStoredToken). */
function token(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function forgetStoredToken(): void {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* nothing stored */ }
}

export function isPaired(): boolean {
  return !!token();
}

function authHeaders(extra?: HeadersInit): HeadersInit | undefined {
  const t = token();
  if (!t) return extra;
  return { ...(extra as Record<string, string> | undefined), "X-Copilot-Token": t };
}

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
    const res = await fetch(`${apiBase()}${path}`, { cache: "no-store", credentials: "include", headers: authHeaders() });
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

export interface IndicatorTile {
  key: string;
  name: string;
  value: string;
  detail: string;
  state: string;
  as_of: string;
  /** Fixed words: what it is, why it is read, how it moves, what it means to a buyer. */
  explain: { what: string; why: string; reacts: string; buyer: string };
  /** Today's reading in words. */
  now: string;
  /** What followed days whose closing reading fell in today's bucket, at today's price. */
  history: IndicatorHistory | null;
}

/** Shares (%) are one per entry of Indicators.targets (points from the next session's open). */
export type IndicatorSide = { n: number; up: (number | null)[]; down: (number | null)[]; either: (number | null)[];
                              median_either_pts: number | null; closed_up_pct: number | null };
export type Versus = "more" | "less" | "like" | "few";
export type IndicatorHistory = {
  bucket: string; like: IndicatorSide; all: IndicatorSide;
  vs_rest: Record<"up" | "down" | "either", Versus[]>; closed_up_vs_rest: Versus;
};

// The grid under the Today chart. `live` means today's candle so far is in
// every reading (provisional until 15:30); `basis` says which candle.
export interface Indicators {
  live: boolean;
  basis: string;
  as_of: string;
  session: string;
  tiles: IndicatorTile[];
  targets: number[];
  history_note: string;
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
  /** "straddle" for the strategy pipeline's two daily straddles, listed beside the patterns. */
  direction: "long" | "short" | "straddle";
  option_type: "CE" | "PE" | "CE+PE";
  status: Verdict;
  verdict_reason: string | null;
  suggested_option: string | null;
  holdout_trades: number;
  holdout_avg_profit_per_lot_rs: number | null;
  /** The straddles are measured per trade in % of the premium paid, not in rupees a lot. */
  holdout_mean_pct?: number | null;
  holdout_t_stat: number | null;
  qualifies: boolean;
  why_not: string | null;
}

export interface EvidenceBar {
  min_t: number;
  patterns_judged: number;
  tests_judged?: number;
  family?: Record<string, number>;
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
  /** Written after its entry session opened — kept, shown, never counted. */
  recorded_late?: boolean;
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
  days_excluded_recorded_late?: number;
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
export const fetchIndicators = () => get<Indicators>("/api/indicators");
export type ChartCandle = {
  /** The 4-hour block's start ("2026-09-25T13:15") and its day. */
  t: string; date: string;
  /** The 13:15 block, which ends at the 15:30 close the patterns are decided on. */
  day_close: boolean;
  open: number; high: number; low: number; close: number;
  /** EMAs of this timeframe's closes, computed in Python over the full history. */
  ema20: number; ema50: number;
  /** Close against the previous candle's close, from Python. */
  change_pct: number | null;
};
export type ChartZone = {
  strategy: string; label: string; side: "call" | "put";
  /** The band a close would have to land in for the pattern to form. */
  low: number; high: number;
  /** False: the close is not enough on its own — the candle also needs `needs` (a long wick…). */
  certain: boolean; needs: string[]; base_rate: number | null;
  condition: "at or above" | "at or below" | "already here";
  edge: number | null; distance_pts: number; distance_pct: number;
};
export type ChartData = {
  as_of: string; sessions: number; source: string; note: string;
  timeframe: "4h"; last_candle: string | null;
  candles: ChartCandle[];
  levels: { session: string; prev_high: number; prev_low: number; last_close: number; reference: number };
  zones: ChartZone[];
  formed: { date: string; strategy: string; label: string; side: "call" | "put" }[];
  /** The 4-hour block still forming, following the live price. */
  live: LiveBar | null;
  /** The 1D view: the indicator grid's daily candles and EMAs, and today's so far. */
  daily: ChartCandle[];
  live_day: LiveBar | null;
  /** The 15m view: the last 10 sessions, and the bar still forming. */
  m15: ChartCandle[];
  live_m15: LiveBar | null;
  /** The 1H view: NSE's hourly blocks from 09:15, the last 30 sessions. */
  h1?: ChartCandle[];
  live_h1?: LiveBar | null;
  /** The 5m view: the last 3 sessions. */
  m5?: ChartCandle[];
  live_m5?: LiveBar | null;
};
export type LiveBar = {
  t: string; date: string; open: number; high: number; low: number; close: number; as_of: string;
  basis?: string; provisional: boolean; change_pct?: number | null;
};
export const fetchChart = () => get<ChartData>("/api/chart");

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

export interface MeanCI { mean: number; low: number; high: number; confidence: number; n: number }
export interface EdgeCI { edge: number; low: number; high: number; includes_zero: boolean; confidence: number }

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
  holdout_ci_95?: MeanCI | null;
  edge_over_no_signal_ci_95?: EdgeCI | null;
  status: Verdict;
  reason: string;
  /** How implied volatility stood when this pattern's options were bought. Description only. */
  iv?: PatternIV | null;
}

export interface PatternIV {
  trades: number;
  median_entry_iv_pct: number | null;
  bought_in_top_half_of_iv: number | null;
  median_contract_iv_at_entry: number | null;
  median_market_iv_change_pts: number | null;
  median_contract_iv_change_pts: number | null;
}

export interface ImpliedVol {
  latest: { date: string; iv_30d_pct: number; percentile_1y: number | null };
  last_year_stats: { median: number; low: number; high: number; days: number };
  vix_check: { compared_days: number; level_correlation?: number; median_gap_points?: number; verdict: string };
  test: { hypothesis: string; registered: string; verdict: string; detail: string };
  last_year: { date: string; iv_30d_pct: number; percentile: number | null }[];
  method_note: string;
}

export const fetchImpliedVol = () => get<ImpliedVol>("/api/iv");

export interface MarketFactor { label: string; move_pct: number; beta: number; contribution_pct: number }
export interface WhyItMoved {
  available: boolean; reason?: string; date?: string; nifty_return_pct?: number; gap_pct?: number;
  intraday_pct?: number; factors?: Record<string, MarketFactor>; explained_by_global_pct?: number;
  unexplained_pct?: number; fit_r2_past_year?: number; fit_window?: string; note?: string;
}
export interface ParticipantNow {
  index_futures_net: number; index_futures_long_share: number | null; index_calls_net: number;
  index_puts_net: number; index_futures_net_change: number | null; futures_long_share_percentile_1y: number | null;
  options_buyer_share: number | null;
}
export interface MarketToday {
  why_it_moved: WhyItMoved;
  options_price_now: { date: string; implied: number; delivered_last_21_sessions: number; note: string } | null;
  expiry: { available: boolean; date?: string; was_expiry?: boolean; next_expiry?: string | null; morning_pct?: number;
            afternoon_pct?: number; last30_pct?: number; sharp_reversal?: boolean; last30_percentile?: number | null;
            pin_distance_points?: number; compared_with?: string };
  unusual_strike_activity: { available: boolean; reason?: string; date?: string; expiry?: string; days_to_expiry?: number;
                             cycles_compared?: number; unusual?: { moneyness_pct: number; type: string; strike_near: number;
                             share_of_volume: number; usual_share: number; z: number }[]; note?: string };
  positioning: { available: boolean; reason?: string; date?: string; by_participant?: Record<string, ParticipantNow>;
                 note?: string };
}
export interface FootprintCompare {
  expiry_sessions: number; other_sessions: number;
  reversal: { expiry_share: number | null; other_share: number | null; z: number | null };
  settlement_window: { expiry_avg_abs_move_pct: number | null; other_avg_abs_move_pct: number | null; t: number | null };
  pinning: { expiry_share_near_strike: number | null; other_share_near_strike: number | null; chance: number; z: number | null };
}
export interface MarketStudies {
  computed_at: string;
  variance_risk_premium: { days: number; period: string; avg_implied: number; avg_delivered: number;
    median_gap_points: number; options_overpriced_share: number;
    by_year: Record<string, { days: number; avg_implied: number; avg_delivered: number; options_overpriced_share: number }>;
    when_sellers_were_hurt: { date: string; implied: number; delivered: number }[]; note: string };
  option_buyers_without_a_signal: { available: boolean; setups?: number; median_rupees_per_lot?: number;
    setups_that_made_money?: number; note?: string };
  global_cues_by_year: Record<string, { sessions: number; r2: number; sp500_beta: number }>;
  expiry_footprints: { all: FootprintCompare; jan_2023_to_mar_2025: FootprintCompare; before_jan_2023: FootprintCompare;
    after_mar_2025: FootprintCompare; definitions: Record<string, string>; caveat: string };
  positioning_history: { available: boolean; days?: number; period?: string;
    by_participant?: Record<string, { days_net_long_index_futures: number; median_options_buyer_share: number | null }>;
    note?: string };
  sebi: Record<string, Record<string, string>>;
}
export interface Principle { id: string; section: string; title: string; principle: string; for_you: string; sources: string[] }
export interface MarketContext { today: MarketToday; studies: MarketStudies | null; knowledge: Principle[] }

export const fetchMarket = () => get<MarketContext>("/api/market");

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
  holdout_ci_95?: MeanCI | null;
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
  holdout_ci_95?: MeanCI | null;
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
    predictive?: boolean;
    verdict: string;
  };
  method_note: string;
}

export const fetchSimilarity = () => get<Similarity>("/api/similarity");

export interface CopilotStatus {
  configured: boolean;
  provider: string;
  model: string | null;
  guards: { numbers: boolean; forecast: boolean; claims: boolean; routing: boolean };
}

export interface CopilotAnswer {
  ok: boolean;
  answer: string | null;
  reason?: string;
  provider: string;
  /** null when the router turned the question away — nothing was generated. */
  model: string | null;
  as_of_close?: string;
  cached?: boolean;
  review?: {
    checked: boolean;
    blocked: boolean;
    scores?: Record<string, number>;
    unsupported?: { claim: string; verdict: string; against: number }[];
    claims_checked?: number;
    reason: string;
  };
  route?: { checked: boolean; route: string | null; off_topic: boolean };
  /** 0-2 on each; recorded and trended, never used to withhold an answer. */
  grades?: { honesty?: number; clarity?: number };
  drafts?: number;
  /** "gemini" = written by the model; "composed" = assembled by the dashboard itself. */
  method?: string;
  /** Set when the provider was down and the composed explanation was served. */
  fallback_from?: string;
}

export const fetchCopilotStatus = () => get<CopilotStatus>("/api/copilot/status");

/** Browser-side calls: these hit a rate-limited free tier, so only on click. */
export async function copilotRequest(path: string, question?: string): Promise<{ data?: CopilotAnswer; error?: string }> {
  try {
    const res = await fetch(`${apiBase()}${path}`, question
      ? { method: "POST", credentials: "include", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ question }) }
      : { cache: "no-store", credentials: "include", headers: authHeaders() });
    const body = await res.json();
    return res.ok ? { data: body as CopilotAnswer } : { error: body.detail ?? `HTTP ${res.status}` };
  } catch {
    return { error: "Backend not reachable." };
  }
}

export type StructuralPeriod = {
  ci_95?: MeanCI | null;
  edge_ci_95?: EdgeCI | null;
  num_trades?: number;
  win_rate?: number;
  avg_profit_per_lot_rs?: number;
  baseline_avg_profit_per_lot_rs: number | null;
  t: number | null;
  by_leg?: Record<string, number>;
};

export type StructuralHypothesis = {
  name: string;
  label: string;
  family: string;
  signal: string;
  why: string;
  hold_sessions: number;
  signals_per_year: number;
  status: "APPROVED" | "CONDITIONAL" | "REJECTED";
  reason: string;
  required_t: number | null;
  development: StructuralPeriod;
  holdout: StructuralPeriod;
};

export type StructuralResearch = {
  computed_at: string;
  period: { start: string; split: string; end: string };
  registered: string;
  trade: string;
  tests_in_family: number;
  hypotheses: StructuralHypothesis[];
  overnight_vs_intraday: {
    since: string;
    sessions: number;
    overnight_total_pct: number;
    intraday_total_pct: number;
    overnight_up_share: number;
    intraday_up_share: number;
  };
};

export const fetchStructural = () => get<StructuralResearch>("/api/structural");

export type JournalDecision = "TOOK" | "SKIPPED" | "WAITED";

export type JournalRow = {
  id: number;
  trade_date: string;
  system_action: string | null;
  decision: JournalDecision;
  underlying: string | null;
  option_type: "CE" | "PE" | null;
  strike: number | null;
  expiry: string | null;
  quantity: number | null;
  entry_premium: number | null;
  exit_premium: number | null;
  exit_date: string | null;
  reason: string | null;
  notes: string | null;
  pnl: { gross_rs: number; costs_rs: number; net_rs: number; return_pct: number } | null;
  followed_system: boolean | null;
  /** 'settled' when held to expiry; a sale otherwise. */
  exit_kind?: string | null;
  stop_premium?: number | null;
  target_premium?: number | null;
  lot_size?: number | null;
  lots?: number | null;
  /** An open trade, priced now. */
  position?: JournalPosition;
  /** Past its expiry: it can be closed at its settlement value. */
  can_settle?: boolean;
};

/** An open trade as it stands, all computed by the API (I2). */
export type JournalPosition = {
  mark: number | null;
  mark_source: string | null;
  mark_at: string | null;
  spot: number | null;
  days_to_expiry: number;
  expired: boolean;
  expires_today: boolean;
  pnl_now?: { gross_rs: number; net_rs: number; return_pct: number };
  intrinsic?: number;
  time_value?: number;
  if_unchanged_at_expiry?: { index: number; value: number; net_rs: number };
  breakeven_index?: number;
  implied_vol_pct?: number;
  decay_per_day_rs?: number;
  plan: { stop: number | null; target: number | null; state: "stop" | "target" | null };
  lines: string[];
};

export type JournalGroup = { decisions?: number; trades: number; net_rs: number; avg_rs: number | null };

export type JournalReport = {
  entries: JournalRow[];
  summary: {
    entries: number;
    by_decision: Record<JournalDecision, number>;
    open_trades: number;
    closed_trades: number;
    net_rs: number;
    win_rate: number | null;
    followed_system: JournalGroup;
    overrode_system: JournalGroup;
    decisions_matching_system: number;
    decisions_with_a_system_verdict: number;
  };
  lot_sizes?: Record<string, number>;
  note: string;
};

/** Browser-side calls for the journal, which the user writes to. */
export async function journalRequest<T>(path: string, method: "GET" | "POST" | "DELETE" = "GET", body?: unknown):
  Promise<{ data?: T; error?: string }> {
  try {
    const res = await fetch(`${apiBase()}${path}`, {
      method,
      cache: "no-store",
      credentials: "include",
      headers: authHeaders(body ? { "Content-Type": "application/json" } : undefined),
      body: body ? JSON.stringify(body) : undefined,
    });
    const json = await res.json();
    if (res.ok) return { data: json as T };
    const detail = Array.isArray(json.detail) ? json.detail.map((d: { msg: string }) => d.msg).join("; ") : json.detail;
    return { error: detail ?? `HTTP ${res.status}` };
  } catch {
    return { error: "Backend not reachable." };
  }
}

export type NewsHypothesis = {
  name: string;
  label: string;
  family: string;
  leg: string;
  signal: string;
  why: string;
  hold_sessions: number;
  signals_since_2018: number;
  signals_per_year: number;
  trades_taken: number;
  development: { num_trades?: number; avg_profit_per_lot_rs?: number; baseline_avg_profit_per_lot_rs?: number | null; t?: number | null };
  holdout: {
    num_trades?: number; avg_profit_per_lot_rs?: number; baseline_avg_profit_per_lot_rs?: number | null;
    win_rate?: number | null; t?: number | null; ci_95?: { low: number; high: number } | null;
  };
  required_t: number | null;
  status: string;
  reason: string;
};

export type NewsResearch = {
  computed_at?: string;
  query_set: string;
  coverage: { days: number; first: string | null; last: string | null };
  tone_days?: number;
  hypotheses: NewsHypothesis[];
  approved: number;
  tested: number;
  tests_in_family: number;
  bar_note?: string;
  prereg_hash: string;
  note: string;
};

export type StrategyFitRow = {
  strategy: string;
  label: string;
  side: "call" | "put";
  /** Python's arithmetic on real prices, never Jev's. */
  status: "forming now" | "formed" | "within reach" | "possible next close";
  pct_to_trigger: number | null;
  trigger_ranges: [number, number][];
  base_rate: number;
  forms_when: string | null;
  why: string | null;
  /** Jev: probability today is the kind of market the premise was written for. Null = unjudged. */
  fit: number | null;
  evidence: { status: string | null; t: number | null; bar: number | null } | null;
};

export type StrategyFit = {
  as_of: string;
  judged: boolean;
  judged_at: string | null;
  note: string | null;
  question_set: string;
  market: {
    index: { level: number; change_today_pct: number | null; as_of: string };
    trend: { classifier: string; ema20: number | null; ema50: number | null; return_20_sessions_pct: number; below_52_week_high_pct: number };
    momentum: { rsi_14: number | null; adx_14: number | null };
    volatility: { india_vix: number | null; implied_vol_30d_percentile_of_past_year: number | null };
  };
  rows: StrategyFitRow[];
  judged_by: string;
  caveat: string;
};

export const fetchStrategyFit = () => get<StrategyFit>("/api/strategy_fit");

export const fetchNewsResearch = () => get<NewsResearch>("/api/news/research");

/** One lot bought now, as the API priced it (options/chain_table.py). */
export type ChainBuyer = {
  price: number;
  price_source: "ask" | "last";
  lot_rs: number;
  buy_charges_rs: number;
  sell_charges_rs: number;
  charges_rs: number;
  spread_rs: number | null;
  breakeven: number;
  needs_move_pts: number;
  needs_move_pct: number;
};

export type ChainContract = {
  identifier: string;
  ltp: number | null;
  change: number | null;
  bid: number | null;
  ask: number | null;
  bid_qty: number;
  ask_qty: number;
  iv: number | null;
  oi: number;
  oi_change: number;
  volume: number;
  /** Positive is out of the money, negative in it. */
  moneyness_pct: number;
  itm: boolean;
  buyer: ChainBuyer | null;
};

export type OptionChainTable = {
  as_of: string;
  underlying_value: number;
  expiry: string;
  expiries: string[];
  days_to_expiry: number;
  atm_strike: number;
  lot_size: number;
  strikes: number;
  rate_card: string;
  /** Where open interest sits in this expiry (options/chain_table.py). */
  open_interest: {
    total_call: number;
    total_put: number;
    pcr: number | null;
    max_call_oi_strike: number | null;
    max_put_oi_strike: number | null;
    call_oi_added: number;
    put_oi_added: number;
  };
  rows: { strike: number; is_atm: boolean; call: ChainContract | null; put: ChainContract | null }[];
};

export const fetchOptionChainTable = (expiry?: string) =>
  get<OptionChainTable>(`/api/options/chain/contracts${expiry ? `?expiry=${encodeURIComponent(expiry)}` : ""}`);

export type NewsRow = {
  id: string;
  title: string;
  summary: string | null;
  url: string | null;
  first_seen: string;
  published_at: string | null;
  source: string;
  source_name: string;
  tier: number;
  phase: string;
  /** Jev: probability this is the kind of event that moves an index.
   *  Null means not yet read — never "judged to be nothing". */
  market_moving: number | null;
  direction: "higher" | "lower" | "unclear" | null;
  dir_conf: number | null;
  topic: string | null;
  /** Python's call: likely to move an index and not a recap. */
  moving?: boolean;
};

export type NewsWindow = {
  label: string;
  means: string;
  rows: NewsRow[];
  older_copy_hidden?: number;
  tone: {
    market_moving: number;
    of_total: number;
    pointing: { higher: number; lower: number; unclear: number };
    topics: Record<string, number>;
    unjudged: number;
  };
};

export type NewsView = {
  phase: string;
  says: string;
  as_of: string;
  session_date: string;
  windows: Record<string, NewsWindow>;
  sources: Record<string, { name: string; tier: number; about: string }>;
  archive: { headlines: number; sessions: number; question_set: string };
  judged_by: string;
  note: string;
  last_pull?: unknown;
};

export const fetchNews = () => get<NewsView>("/api/news");

export type GiftNifty = {
  symbol: string;
  expiry: string;
  last: number;
  previous_close: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  last_trade_time: string;
  snapshots_archived: number;
  note: string;
};

export const fetchGiftNifty = () => get<GiftNifty>("/api/gift-nifty");

export type IndexRow = {
  key: "nifty" | "banknifty" | "sensex" | "gift";
  name: string;
  last: number;
  previous_close: number;
  change: number;
  change_pct: number;
  /** "+77.40 (+0.34%)", written by the API with a real minus sign. */
  change_text: string;
  open: number | null;
  high: number | null;
  low: number | null;
  /** Where the last price sits in the day's range, 0 = low, 100 = high. */
  day_position: number | null;
  as_of: string | null;
  source: string;
  /** Minutes behind the other spot indices, in a session. */
  behind: boolean;
};

export type IndicesBoard = {
  market_open: boolean;
  as_of: string;
  rows: IndexRow[];
  /** Sentences written in Python from the numbers: what moved, never what to do. */
  commentary: string[];
};

export const fetchIndices = () => get<IndicesBoard>("/api/indices");

export type ReplicationSide = { trades: number; avg_return_pct: number | null; win_rate: number | null };

export type ReplicationHypothesis = {
  kind: "pattern" | "structural";
  name: string;
  label: string;
  setup: string;
  status: "APPROVED" | "CONDITIONAL" | "REJECTED";
  reason: string;
  pooled: {
    development_dates: number; holdout_dates: number;
    development_avg_pct: number; holdout_avg_pct: number;
    baseline_development_avg_pct: number; baseline_holdout_avg_pct: number;
    holdout_t: number | null; required_t: number | null;
    holdout_edge_pct: number;
    holdout_ci_95: MeanCI | null; edge_ci_95: EdgeCI | null;
  };
  per_index: Record<string, { development: ReplicationSide; holdout: ReplicationSide;
    holdout_edge_pct: number | null;
    baseline_holdout_avg_pct: number | null; baseline_development_avg_pct: number | null }>;
  indices_beating_baseline_in_holdout: number;
  indices_with_holdout_trades: number;
};

export type Replication = {
  computed_at: string;
  registered: string;
  measure: string;
  unit: string;
  tests_counted: number;
  coverage: Record<string, { index_days: number; first: string; last: string }>;
  hypotheses: ReplicationHypothesis[];
};

export const fetchReplication = () => get<Replication>("/api/replication");

export type CoursePeriod = {
  num_trades: number; mean_pct: number; median_pct: number; win_rate: number;
  baseline_mean_pct: number | null; t_vs_baseline: number | null;
  index_points_mean: number | null; index_win_rate: number | null;
};
export type CourseRow = {
  name: string; label: string; verdict: "APPROVED" | "CONDITIONAL" | "REJECTED"; reason: string;
  required_t: number | null; timeframe: string;
  /** The period the verdict rests on: 2024–26 for the course, 2015–17 for the breakout pair. */
  judged: string;
  periods: Record<string, CoursePeriod | null>;
};
export type CourseResearch = {
  computed_at: string; prereg: { course: string; breakout: string | null }; tests_in_family: number; rows: CourseRow[];
};
export const fetchCourseResearch = () => get<CourseResearch>("/api/course_research");

export type PipelineRow = CourseRow & { rule: string };
export type NiftyPipeline = {
  computed_at: string; prereg: string; tests_in_family: number; rows: PipelineRow[];
  /** Phase 1: the cost of one point of NIFTY exposure a session, at the money, 2019–23 only. */
  instrument: {
    period: { from: string; to: string; sessions: number; note: string };
    rule: string;
    chosen: { expiry: string; moneyness: string };
    chosen_without_slippage: { expiry: string; moneyness: string };
    rows: { expiry: "nearest" | "monthly"; hold: number; carry_pts: number | null; carry_pts_without_slippage: number | null;
            /** The same with the half-spreads the option snapshots measured, once that run exists. */
            carry_pts_measured?: number | null }[];
    /** Phase 1 re-run at real half-spreads (scripts/instrument_study.py --measured-spreads); null until run. */
    measured?: { sessions: string[]; window: string; basis: "close" | "all_day";
                 chosen: { expiry: string; moneyness: string } | null; chosen_atm: string | null; caveat: string } | null;
  } | null;
  /** The order-flow rules registered for a forward test on the option snapshots. */
  forward?: {
    prereg: string; registered_on: string; tests_in_family: number;
    rows: { name: string; label: string; status: "waiting" | "judged"; sessions: number | null; min_sessions: number | null;
            counted_trades: number | null; min_trades: number | null; verdict?: Verdict | null; reason: string | null }[];
  } | null;
};
export const fetchNiftyPipeline = () => get<NiftyPipeline>("/api/nifty_pipeline");

export type IntradayContract = { expiry: string; strike: number; option_type: "CE" | "PE" };
export type IntradayRule = {
  name: string;
  label: string;
  status: "waiting" | "in_trade" | "closed" | "no_trade" | "no_history";
  side?: 1 | -1 | null;
  entry_time?: string; exit_time?: string; exit_reason?: string;
  entry_index?: number; exit_index?: number;
  /** When the rule next acts, and (noise band) the levels it acts on. */
  next?: { at: string; upper?: number; lower?: number } | null;
  entry_levels?: { at: string; upper: number; lower: number };
  first_half_hour_pct?: number;
  first_half_hour_pts?: number;
  previous_close?: number;
  /** Sessions the noise band needs whose 5-minute bars are missing. */
  missing?: string[];
  first_candle?: { open: number; high: number; low: number; close: number };
  stop?: number;
  contract?: IntradayContract | null;
  evidence: { verdict: Verdict; required_t: number | null; holdout_t: number | null; holdout_mean_pct: number | null;
              holdout_baseline_pct: number | null; holdout_trades: number | null } | null;
  /** The sentence to show, written by the API; "Consider" only for an APPROVED rule. */
  line: string;
  /** The rule's record at real option prices from 1 Oct 2026. */
  forward: { trades: number; recorded: number; mean_pct: number | null; first_day: string } | null;
  recorded_today: { kind: "entry" | "exit"; bar_close_at: string; price_at: string | null; bid: number | null;
                    ask: number | null; ltp: number | null }[];
};
export type Intraday = {
  session: string | null; bars_through: string; as_of: string; source: string; note: string; rules: IntradayRule[];
  /** Sessions after `session` that the daily archive has but the 5-minute bars do not. */
  missing_after?: string[];
};
export const fetchIntraday = () => get<Intraday>("/api/intraday");

export type WeekdayShape = {
  sessions: number; since: string; ref: number; range: number | null; range_pct: number; up_from_open: number | null; down_from_open: number | null;
  open_to_close: number | null; up_first_pct: number; first_up: number | null; back_after_up: number | null;
  first_down: number | null; back_after_down: number | null; first_swing_ends: string | null;
  swings_per_day: number | null;
  path: { at: string; median: number | null; p25: number | null; p75: number | null }[];
};
export type WeekdayProfile = {
  as_of: string; session: string; weekday: string; expiry: boolean; bars_source: string; swing_pct: number;
  /** The level every session's % of its open is shown at, in points. */
  reference: { level: number | null; is: string };
  profile: WeekdayShape | null; all_days: WeekdayShape | null; expiry_profile: WeekdayShape | null;
  today: { open: number; through: string | null; up: number; down: number; now: number;
           path: { at: string; points: number }[];
           swings: { dir: 1 | -1; points: number; ends: string | null; done: boolean }[] } | null;
  similar: { through: string; rose_after: number; fell_after: number; note: string;
             days: { date: string; match_pct: number; at_last: number; after: number; expiry: boolean }[] } | null;
  why: string[];
  indicators: { label: string; verdict: Verdict; holdout_t: number | null; required_t: number | null }[];
  note: string;
};
export const fetchWeekdayProfile = () => get<WeekdayProfile>("/api/weekday_profile");

export type MoveCell = {
  flat: number; flat_pct: number;
  up: Record<string, number>; down: Record<string, number>;
  up_pct: Record<string, number>; down_pct: Record<string, number>;
};
export type MoveLeg = {
  price: number; basis: "mid" | "last" | null; iv: number | null; delta: number | null;
  up: Record<string, number>; down: Record<string, number>;
  up_pct?: Record<string, number>; down_pct?: Record<string, number>;
  /** The same moves by each horizon's close, with that much less time to expiry. */
  at?: Record<string, MoveCell>;
};
export type OptionMoves = {
  as_of: string; spot: number; expiry: string; expiries: string[]; days_to_expiry: number; moves: number[];
  forward?: number; forward_basis?: string; holidays_known?: boolean;
  horizons?: { key: string; label: string; at: string; hours_from_now: number }[];
  rows: { strike: number; is_atm: boolean; call: MoveLeg | null; put: MoveLeg | null;
          call_measured: number | null; put_measured: number | null }[];
  measured_session: string | null; measured_snapshots: number; note: string;
};
export const fetchOptionMoves = () => get<OptionMoves>("/api/options/moves");

export type DayForecastBody = {
  target: string; prev: string; prev_close: number; iv30: number; sigma_raw_pct: number; k: number;
  tag_multiplier: number; sigma_pct: number; sigma_pts: number; band68: [number, number]; band95: [number, number];
  expected_range_pts: number; tags: string[];
  lean: { side: "up" | "down"; p_up: number; sessions: number; basis: string };
  /** Present from 2026-10-06: which way the band was sized, and where its IV came from. */
  method?: string; method_label?: string; iv_source?: string;
};
export type ForecastMethodChoice = {
  decided_on: string; made_at: string;
  choice: { champion: string; previous: string; switched: boolean; sessions: number; trial: number; margin: number;
            scores: Record<string, number>; reason: string; labels: Record<string, string> };
};
export type DayOutcome = {
  open: number; high: number; low: number; close: number; move_pts: number; move_pct: number; z: number;
  inside68: boolean; inside95: boolean; range_pts: number; range_vs_expected: number | null; lean_hit: boolean;
  missed: boolean; why: string[];
};
export type DayForecastRecord = { target_day: string; made_at: string; forecast: DayForecastBody;
                                  scored_at: string | null; outcome: DayOutcome | null };
export type DayForecast = {
  next: DayForecastRecord | null; recent: DayForecastRecord[];
  summary: { forecasts: number; inside68_pct: number; inside95_pct: number; lean_hit_pct: number; first: string } | null;
  hindcast: { k_dev?: number; holdout_inside68_pct?: number; holdout_inside95_pct?: number; holdout_lean_hit_pct?: number };
  calibration_now: { k: number; window: number; multipliers: { event: number; expiry: number }; range_ratio: number };
  status: { due: string; stale: boolean; waiting: boolean; reasons: string[] };
  accuracy: { forecasts: number; inside68_pct: number; inside95_pct: number; lean_hit_pct: number;
              width_ratio: number; width_reading: string; mean_abs_move_pts: number } | null;
  learning: { latest: ForecastMethodChoice | null; switches: ForecastMethodChoice[] };
  note: string;
};
export const fetchDayForecast = () => get<DayForecast>("/api/day_forecast");

export type LiveLeg = { price: number; change: number; change_pct: number };
export type OptionMovesLive = {
  index: number; move: number; prices_as_of: string; expiry: string;
  rows: { strike: number; is_atm: boolean; call: LiveLeg | null; put: LiveLeg | null }[];
};

export type LoginDay = {
  trade_date: string;
  status: "LOGGED_IN" | "PROMPTED" | "MISSING";
  issued_at: string | null;
  checked_at: string;
  note: string | null;
};

export type ZerodhaStatus = {
  configured: { api_key: boolean; api_secret: boolean };
  logged_in: boolean;
  reason?: string;
  issued_at?: string;
  history: {
    days_recorded: number;
    days_logged_in: number;
    days_without_a_session: number;
    current_streak: number;
    last_login: string | null;
    last_login_at: string | null;
    recent: LoginDay[];
  };
};

export const fetchZerodhaStatus = () => get<ZerodhaStatus>("/api/zerodha/status");
export const zerodhaLoginUrl = () => `${apiBase()}/api/zerodha/login`;

export type PaperPnl = {
  gross_pct: number; net_pct: number | null; profit_rs: number; invested_rs: number; lots: number;
  profit_per_lot_rs: number; realised: boolean; live: boolean;
};

export type PaperTrade = {
  id: number;
  source: "pattern" | "control";
  strategy: string;
  label: string;
  signal_date: string;
  option_type: "CE" | "PE";
  strike: number;
  expiry: string;
  entry_date: string;
  entry_premium: number;
  hold_days: number;
  planned_exit: string | null;
  exit_date: string | null;
  exit_premium: number | null;
  mark_date: string | null;
  mark_premium: number | null;
  status: "OPEN" | "CLOSED";
  lots: number;
  pnl: PaperPnl | null;
};

export type PaperSide = {
  closed: number; avg_net_pct: number | null; total_rs: number; total_per_lot_rs: number;
  win_rate: number | null; open: number;
};

export type PaperAccount = {
  allocated_rs: number; cash_rs: number; equity_rs: number; realised_rs: number;
  open_positions_value_rs: number; return_pct: number | null; max_per_trade_rs: number;
  max_per_trade_share: number; flows: { id: number; ts: string; amount: number; note: string | null }[];
};

export type EquityPoint = { date: string; equity_rs: number; change_rs: number; what: string; pnl_rs?: number };

export type PaperObjective = {
  goal: string; allocated_rs: number; equity_rs: number; profit_rs: number; growth_pct: number | null;
  pnl_high_rs: number; below_high_water_rs: number; sizing_note: string; containment: string;
};

export type PaperReport = {
  /** The book: at most one position a session. */
  trades: PaperTrade[];
  /** The yardstick, priced on the same premiums but outside the book — it
   *  spends none of the allocated money and never takes the session's slot. */
  benchmark?: PaperTrade[];
  /** The latest evening's decision, including what it did not do and why. */
  last_decision?: {
    run_at: string; entry_session: string; signal_session: string;
    opened: string[]; skipped: string[]; passed_over: string[]; benchmark_opened: string[]; note: string | null;
    /** Each strike comparison made that evening, with its one-line reason. */
    choices?: { for: string; summary: string }[];
  } | null;
  account: PaperAccount;
  equity_curve: EquityPoint[];
  objective: PaperObjective;
  summary: {
    observing_since: string | null;
    started: string;
    patterns: PaperSide;
    best_read: PaperSide;
    control: PaperSide;
    book_closed?: number;
    sessions_needed_before_this_means_anything: number;
  };
  note: string;
};

export const fetchPaper = () => get<PaperReport>("/api/paper");

export type LiveTick = {
  as_of: string;
  market: { is_open: boolean | null; status?: string; trade_date?: string; open_by_clock?: boolean };
  index: number | null;
  previous_close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  source: string | null;
  /** When the price itself was taken — not when this response was built. */
  quote_at?: string | null;
  age_s?: number | null;
  stale?: boolean;
  /** Set here, not by the API: the last tick, re-sent when the API stopped answering. */
  offline?: boolean;
  marks: Record<string, number>;
  paper?: {
    allocated_rs: number; cash_rs: number; equity_rs: number; realised_rs: number;
    open_positions_value_rs: number; return_pct: number | null; max_per_trade_rs: number;
    open_positions: number; live_priced: number; unrealised_rs: number;
  } | null;
  /** The Market tab's indices board, from what the API had in hand. */
  indices?: IndicesBoard | null;
  /** The journal's open trades, priced on the same Kite answer, by entry id. */
  journal?: Record<string, JournalPosition> | null;
  /** The option-move card's contracts repriced at the index now (in a session). */
  option_moves_live?: OptionMovesLive | null;
  /** Today's intraday-rule contracts, priced on the same answer, by rule name. */
  intraday?: { marks: Record<string, number>; at: string | null } | null;
};

export const fetchTick = () => get<LiveTick>("/api/live/tick");

/** One poller for the whole page.
 *
 *  Three components used to run three timers against the same endpoint. This
 *  keeps a single interval, hands every subscriber the same tick, and stops
 *  when the last one goes away. Cadence follows the market: 2s open, 60s shut. */
type TickListener = (tick: LiveTick) => void;
const listeners = new Set<TickListener>();
let timer: ReturnType<typeof setTimeout> | null = null;
// True from the moment a loop is scheduled until it finds nobody listening.
// Starting a loop is only ever decided by this flag, so no pattern of mounts,
// unmounts or re-subscribes during a delivery can start a second one.
let running = false;
let latest: LiveTick | null = null;

async function pump() {
  timer = null;
  if (listeners.size === 0) { running = false; return; }
  // A background tab has nobody reading it: check back, but ask nothing.
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    timer = setTimeout(pump, 5000);
    return;
  }
  const r = await fetchTick();
  if (r.data) {
    latest = r.data;
    listeners.forEach((fn) => fn(r.data as LiveTick));
  } else if (latest && !latest.offline) {
    // The API stopped answering. Say so, rather than leave the last price
    // standing as if it were still current.
    latest = { ...latest, offline: true, stale: true };
    listeners.forEach((fn) => fn(latest as LiveTick));
  }
  if (listeners.size === 0) { running = false; return; }
  const open = r.data?.market?.is_open ?? r.data?.market?.open_by_clock;
  timer = setTimeout(pump, open ? 2000 : 60000);
}

export function subscribeToTick(fn: TickListener): () => void {
  listeners.add(fn);
  if (latest) fn(latest);
  if (!running) {
    running = true;
    timer = setTimeout(pump, 0);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0 && timer) {
      clearTimeout(timer);
      timer = null;
      running = false;
    }
  };
}


export type Pairing = {
  token: string;
  hosts: string[];
  links: string[];
  note: string;
  exposed: boolean;
};

/** Only answers on the Mac — the token is shown where it belongs. */
export const fetchPairing = () => get<Pairing>("/api/access/pairing");

/** Whether every card's data is current, from the watchdog's last check
 *  (briefing/freshness.py, scripts/freshness_check.py). */
export type FreshnessSource = {
  key: string; card: string; path: string; kind: string; status: "current" | "behind" | "unavailable" | "on demand";
  as_of: string | null; reason: string; fix: string[];
};
export type Freshness = {
  checked_at: string; check_age_min: number | null; sources: FreshnessSource[];
  current: number; behind: number; unavailable: number; on_demand: number;
  services: { service: string; started: string | null; on_disk: string | null; behind: boolean; action: string | null }[];
  fixes_run: { fix: string; ok: boolean }[]; nightly_job_running: boolean;
};
export const fetchFreshness = () => get<Freshness>("/api/freshness");

/** The sentinel (api/sentinel/): incidents open and recent, each with the repairs tried. */
export type Incident = {
  id: number; check_key: string; area: string; severity: "info" | "warn" | "critical"; opened_at: string;
  summary: string; seen_count: number; last_seen: string; resolved_at: string | null;
  repairs: { at: string; detail: string }[];
};
export type Sentinel = { checked_at: string | null; mode: string | null; open: Incident[]; recent: Incident[]; ntfy: boolean };
export const fetchSentinel = () => get<Sentinel>("/api/sentinel");

/** Today's breakout levels (briefing/breakout_levels.py). */
export type BreakoutSummary = { n: number; held_30_pct: number | null; failed_pct: number | null;
                                median_pts_30: number | null; median_pts_close: number | null };
export type BreakoutRecord = Partial<Record<"up" | "down", { all: BreakoutSummary; recent: BreakoutSummary }>>;
export type BreakoutEvent = {
  level: string; direction: "up" | "down"; at: string; bar_close_at: string; close: number; level_price: number;
  outcome: { pts_15: number | null; pts_30: number | null; pts_60: number | null; pts_close: number | null;
             held_30: boolean | null; failed: boolean | null;
             travel_5?: number | null; travel_15?: number | null; travel_30?: number | null; travel_60?: number | null };
  option: { expiry: string; strike: number; option_type: string; ask: number | null; bid: number | null;
            price_at: string; on_time: number } | null;
};
/** Per horizon (minutes, as a string): breaks counted, and the share (%) that went at least each target. */
export type BreakoutSlice = { n: Record<string, number>; pct: Record<string, (number | null)[]> };
export type BreakoutOdds = { all: BreakoutSlice; like_today: BreakoutSlice };
export type BreakoutVersus = { all: Record<string, Versus[]>; like_today: Record<string, Versus[]> };
export type BreakoutLevel = {
  key: string; label: string; price: number; distance_pts: number | null; state: string; since: string | null;
  failed: boolean | null; opened: "above" | "below" | null; events: BreakoutEvent[]; record: BreakoutRecord | null;
  forward: Partial<Record<"up" | "down", { n: number; scored: number; held_30_pct: number | null;
                                           median_option_pct_30: number | null; option_counted: number }>> | null;
  beyond_random: boolean;
  plain: { where: string; today: string; watch: "up" | "down" | null };
  odds?: Record<"up" | "down", BreakoutOdds>;
  vs_random?: Record<"up" | "down", BreakoutVersus>;
};
export type Breakouts = {
  session: string; bars_through: string | null; last_close: number | null; source: string | null; as_of: string;
  levels: BreakoutLevel[]; baseline: BreakoutRecord | null;
  record: { computed_at: string | null; since: string | null; sessions: number | null; breaks: number | null };
  note: string;
  opened: "gap up" | "gap down" | "flat" | null;
  baseline_odds: Record<"up" | "down", BreakoutOdds> | null;
  targets: number[]; horizons: string[];
  summary: { head: string; edge: string; better: string[] };
  travel_as_of: string | null;
  /** Every level, highest first, with levels at one price merged ("Yesterday's high & close"). */
  levels_merged: (BreakoutLevel & { keys: string[] })[];
  /** The nearest level above NIFTY and the nearest below. */
  key_levels: { resistance: KeyLevel | null; support: KeyLevel | null };
  entry: BreakoutEntry | null;
};
export type KeyLevel = { key: string; label: string; price: number };
export type EntryWindow = { need_pts: number | null; pct: number | null; n: number; random_pct: number | null;
                            random_n: number; verdict: Versus };
export type EntrySide = {
  key: string; label: string; price: number; distance_pts: number; direction: "up" | "down";
  option: { kind: "CE" | "PE"; strike: number; expiry: string; premium: number; price_source: string };
  windows: Record<string, EntryWindow>;
};
export type BreakoutEntry = { resistance: EntrySide | null; support: EntrySide | null; error: string | null };
export const fetchBreakouts = () => get<Breakouts>("/api/breakouts");

/** Before you buy (briefing/precheck.py): one contract measured, never judged. */
export type PrecheckWindow = "15m" | "30m" | "60m" | "close" | "1s" | "2s" | "3s" | "5s" | "expiry";
export type Precheck = {
  as_of: string; chain_as_of: string; spot: number; forward_basis: string; window: PrecheckWindow; window_label: string;
  price_source: string; marked: number; note: string;
  contract: {
    kind: "CE" | "PE"; strike: number; expiry: string; premium: number; bid: number | null; ask: number | null;
    lots: number; quantity: number; forward: number; direction: "up" | "down"; iv: number | null; exit_at: string;
    paid_rs: number; buy_charges_rs: number; charges_rs: number; charges_pct: number;
    spread_rs: number | null; spread_pct: number | null; sell_now_rs: number | null;
    flat_rs: number; flat_pct: number; value_flat: number; breakeven_pts: number | null;
  };
  history: { touch_pct: number | null; end_pct: number | null; n: number; basis: string };
  forecast: { target_day: string; sigma_pts: number | null; band68: number[] | null } | null;
  checks: { key: string; tone: "warn" | "info"; text: string }[];
};
export const fetchPrecheck = (q: URLSearchParams) => journalRequest<Precheck>(`/api/precheck?${q.toString()}`);
