// Placeholder data only — Phase 2 (UI shell). None of this is computed or real.
// Real numbers arrive in Phase 5+ from the Python quant engine, never invented here.

export type Regime = "TREND_BULL" | "TREND_BEAR" | "RANGE" | "TRANSITION";

export interface IndicatorReading {
  name: string;
  value: string;
  read: "supports" | "conflicts" | "neutral";
}

export interface ScenarioEvidence {
  sampleSize: number;
  winRate: number;
  medianForwardReturn: number;
}

export interface Scenario {
  kind: "bullish" | "bearish" | "no_trade";
  headline: string;
  entryZone?: string;
  target?: string;
  stopLoss?: string;
  rewardRisk?: string;
  confirmation: string[];
  invalidation: string[];
  evidence?: ScenarioEvidence;
  why: string[];
}

export const mockSnapshot = {
  symbol: "NIFTY 50",
  price: 24812.35,
  change: 104.2,
  changePct: 0.42,
  asOf: "15:15 IST candle close",
  provisional: false,
  regime: "TREND_BULL" as Regime,
};

export const mockIndicators: IndicatorReading[] = [
  { name: "EMA 20 vs EMA 50", value: "EMA20 above EMA50", read: "supports" },
  { name: "VWAP", value: "Price 0.3% above VWAP", read: "supports" },
  { name: "RSI (14)", value: "58", read: "neutral" },
  { name: "ADX (14)", value: "27 (trending)", read: "supports" },
  { name: "ATR (14)", value: "142 pts", read: "neutral" },
  { name: "Relative Volume", value: "1.3x 20-day average", read: "supports" },
  { name: "India VIX", value: "13.1", read: "neutral" },
];

export const mockScenarios: Scenario[] = [
  {
    kind: "bullish",
    headline: "Pullback-to-VWAP continuation",
    entryZone: "24,760 – 24,790",
    target: "24,980",
    stopLoss: "24,690",
    rewardRisk: "1 : 2.4",
    confirmation: [
      "15-min candle closes back above VWAP with relative volume > 1.2x",
      "RSI holds above 45 on the pullback (no momentum breakdown)",
    ],
    invalidation: [
      "15-min close below 24,690 (prior swing low)",
      "ADX drops below 20 (trend losing strength)",
    ],
    evidence: { sampleSize: 46, winRate: 0.61, medianForwardReturn: 0.9 },
    why: [
      "Trend: EMA20 > EMA50, both sloping up — structurally bullish.",
      "Price action: higher-high / higher-low sequence intact since morning session.",
      "VWAP: price holding above VWAP all session, pullbacks have been shallow.",
      "Volume: relative volume above average on up-moves, below average on pullbacks — healthy participation pattern.",
      "Historical evidence: 46 similar occurrences (TREND_BULL + VWAP pullback + ADX>25) — placeholder sample, not yet computed from real data.",
    ],
  },
  {
    kind: "bearish",
    headline: "Failure at prior-day high",
    entryZone: "24,860 – 24,880",
    target: "24,700",
    stopLoss: "24,930",
    rewardRisk: "1 : 2.1",
    confirmation: [
      "Rejection candle at prior-day high with fade in relative volume",
      "RSI turns down from above 65",
    ],
    invalidation: [
      "15-min close above 24,930 (clean breakout, no rejection)",
    ],
    evidence: { sampleSize: 21, winRate: 0.44, medianForwardReturn: -0.3 },
    why: [
      "Conflicting evidence: this scenario fights the prevailing TREND_BULL regime, which is why its sample win rate is weaker.",
      "Price action: prior-day high has acted as resistance twice this week.",
      "Momentum: RSI approaching overbought territory near this level historically.",
      "This is shown to illustrate the UI, not as a live recommendation.",
    ],
  },
  {
    kind: "no_trade",
    headline: "Insufficient edge until 15-min candle confirms direction",
    confirmation: [],
    invalidation: [],
    why: [
      "Sample sizes for both scenarios above are small (placeholder data) — a real system would require much larger out-of-sample evidence before calling either scenario validated.",
      "The system is designed to default to NO TRADE whenever evidence is weak, rather than manufacture a setup.",
    ],
  },
];
