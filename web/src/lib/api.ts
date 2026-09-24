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
  const { protocol, hostname } = window.location;
  if (hostname === "localhost" || hostname === "127.0.0.1") return "http://localhost:8000";
  return `${protocol}//${hostname}:8000`;
}

const TOKEN_KEY = "copilot_token";

/** The pairing token, kept in this browser only. A link carrying ?token=...
 *  stores it once and is stripped from the address bar, so it does not sit
 *  in history or get shared by accident. */
function token(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const url = new URL(window.location.href);
    const fromLink = url.searchParams.get("token");
    if (fromLink) {
      localStorage.setItem(TOKEN_KEY, fromLink);
      url.searchParams.delete("token");
      window.history.replaceState({}, "", url.toString());
      return fromLink;
    }
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
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
    const res = await fetch(`${apiBase()}${path}`, { cache: "no-store", headers: authHeaders() });
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
      ? { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ question }) }
      : { cache: "no-store", headers: authHeaders() });
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
};

export type JournalGroup = { trades: number; net_rs: number; avg_rs: number | null };

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
  note: string;
};

/** Browser-side calls for the journal, which the user writes to. */
export async function journalRequest<T>(path: string, method: "GET" | "POST" | "DELETE" = "GET", body?: unknown):
  Promise<{ data?: T; error?: string }> {
  try {
    const res = await fetch(`${apiBase()}${path}`, {
      method,
      cache: "no-store",
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

export type OptionChain = {
  as_of: string;
  underlying_value: number;
  expiry: string;
  available_expiries: string[];
  atm_strike: number;
  atm_iv: { call: number | null; put: number | null };
  open_interest: {
    total_call: number;
    total_put: number;
    pcr: number | null;
    max_call_oi_strike: number | null;
    max_put_oi_strike: number | null;
    call_oi_added: number;
    put_oi_added: number;
    ladder: {
      strike: number;
      call_oi: number;
      call_oi_change: number;
      put_oi: number;
      put_oi_change: number;
      is_atm: boolean;
    }[];
    ladder_each_side: number;
    peaks_shown: boolean;
  };
  strikes_analysed: number;
  notes: string[];
  interpretation_caveat: string;
};

export const fetchOptionsChain = () => get<OptionChain>("/api/options/chain");

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
};

export type NewsWindow = {
  label: string;
  means: string;
  rows: NewsRow[];
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

export type EquityPoint = { date: string; equity_rs: number; change_rs: number; what: string };

export type PaperObjective = {
  goal: string; allocated_rs: number; equity_rs: number; profit_rs: number; growth_pct: number | null;
  high_water_rs: number; below_high_water_rs: number; sizing_note: string; containment: string;
};

export type PaperReport = {
  /** The book: at most one position a session. */
  trades: PaperTrade[];
  /** The yardstick, priced on the same premiums but outside the book — it
   *  spends none of the allocated money and never takes the session's slot. */
  benchmark?: PaperTrade[];
  account: PaperAccount;
  equity_curve: EquityPoint[];
  objective: PaperObjective;
  summary: {
    observing_since: string | null;
    started: string;
    patterns: PaperSide;
    best_read: PaperSide;
    control: PaperSide;
    sessions_needed_before_this_means_anything: number;
  };
  note: string;
};

export const fetchPaper = () => get<PaperReport>("/api/paper");

export type LiveTick = {
  as_of: string;
  market: { is_open: boolean | null; status?: string; trade_date?: string };
  index: number | null;
  previous_close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  source: string | null;
  marks: Record<string, number>;
  paper?: {
    allocated_rs: number; cash_rs: number; equity_rs: number; realised_rs: number;
    open_positions_value_rs: number; return_pct: number | null; max_per_trade_rs: number;
    open_positions: number; live_priced: number; unrealised_rs: number;
  } | null;
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
let latest: LiveTick | null = null;

async function pump() {
  const r = await fetchTick();
  if (r.data) {
    latest = r.data;
    listeners.forEach((fn) => fn(r.data as LiveTick));
  }
  if (listeners.size === 0) { timer = null; return; }
  timer = setTimeout(pump, r.data?.market?.is_open ? 2000 : 60000);
}

export function subscribeToTick(fn: TickListener): () => void {
  listeners.add(fn);
  if (latest) fn(latest);
  if (!timer) timer = setTimeout(pump, 0);
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0 && timer) { clearTimeout(timer); timer = null; }
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
