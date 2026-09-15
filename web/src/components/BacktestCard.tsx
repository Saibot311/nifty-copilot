import type { BacktestResult } from "@/lib/api";
import { Offline, Panel, Pill, Stat, fmtPct } from "./ui";

export function BacktestCard({ result }: { result: BacktestResult | null }) {
  if (!result) return <Offline what="Backtest" />;

  const m = result.metrics;
  if (!m.num_trades) {
    return (
      <Panel className="p-4 text-sm text-zinc-500">
        {m.note ?? "No trades generated for this strategy over this period."}
      </Panel>
    );
  }

  const positive = (m.expectancy_pct ?? 0) >= 0;

  return (
    <Panel className="p-4">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-zinc-200">EMA Pullback</div>
          <div className="mt-0.5 text-[11px] text-zinc-600">
            {result.symbol} · {result.period.start} → {result.period.end} · {result.period.bars} daily bars
          </div>
        </div>
        <Pill tone="warn">Exploratory — not validated</Pill>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Trades" value={m.num_trades} />
        <Stat label="Expectancy / trade" value={fmtPct(m.expectancy_pct)} tone={positive ? "good" : "bad"} />
        <Stat
          label="Profit factor"
          value={m.profit_factor?.toFixed(2) ?? "–"}
          tone={(m.profit_factor ?? 0) >= 1 ? "good" : "bad"}
        />
        <Stat label="Max drawdown" value={fmtPct(m.max_drawdown_pct, 1)} tone="bad" />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-zinc-800/70 pt-4 sm:grid-cols-4">
        <Stat
          label="Win rate"
          value={m.win_rate != null ? `${Math.round(m.win_rate * 100)}%` : "–"}
          tone="muted"
        />
        <Stat label="Sharpe (approx)" value={m.sharpe_ratio_approx?.toFixed(2) ?? "–"} tone="muted" />
        <Stat label="Sortino (approx)" value={m.sortino_ratio_approx?.toFixed(2) ?? "–"} tone="muted" />
        <Stat label="Avg hold" value={m.avg_holding_days ? `${m.avg_holding_days}d` : "–"} tone="muted" />
      </div>

      {m.sample_size_warning && (
        <p className="mt-4 rounded-lg bg-zinc-950/60 p-3 text-[11px] leading-relaxed text-amber-200/80">
          {m.sample_size_warning}
        </p>
      )}
    </Panel>
  );
}
