import type { BacktestResult } from "@/lib/api";

export function BacktestCard({ result, live }: { result: BacktestResult | null; live: boolean }) {
  if (!live || !result) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 text-sm text-zinc-500">
        Backtest results unavailable — the backend API isn&apos;t reachable right now.
      </div>
    );
  }

  const m = result.metrics;
  if (!m.num_trades) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 text-sm text-zinc-500">
        {m.note ?? "No trades generated for this strategy over this period."}
      </div>
    );
  }

  const positive = (m.expectancy_pct ?? 0) >= 0;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-indigo-400">
            Backtest — EMA Pullback
          </div>
          <div className="text-xs text-zinc-500 mt-0.5">
            {result.symbol} · {result.period.start} to {result.period.end} · {result.period.bars} daily bars
          </div>
        </div>
        <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-300">
          Exploratory — not validated
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Trades" value={String(m.num_trades)} />
        <Stat
          label="Expectancy / trade"
          value={fmtPct(m.expectancy_pct)}
          tone={positive ? "good" : "bad"}
        />
        <Stat
          label="Profit factor"
          value={m.profit_factor != null ? m.profit_factor.toFixed(2) : "n/a"}
          tone={m.profit_factor != null ? (m.profit_factor >= 1 ? "good" : "bad") : "neutral"}
        />
        <Stat label="Max drawdown" value={fmtPct(m.max_drawdown_pct)} tone="bad" />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Win rate" value={m.win_rate != null ? `${Math.round(m.win_rate * 100)}%` : "n/a"} />
        <Stat label="Sharpe (approx)" value={m.sharpe_ratio_approx?.toFixed(2) ?? "n/a"} />
        <Stat label="Sortino (approx)" value={m.sortino_ratio_approx?.toFixed(2) ?? "n/a"} />
        <Stat label="Avg hold" value={m.avg_holding_days ? `${m.avg_holding_days}d` : "n/a"} />
      </div>

      {m.sample_size_warning && (
        <div className="mt-4 rounded-lg bg-zinc-950/60 p-2.5 text-xs text-zinc-400">
          ⚠ {m.sample_size_warning}
        </div>
      )}
    </div>
  );
}

function fmtPct(v?: number) {
  if (v == null) return "n/a";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" | "neutral" }) {
  const color =
    tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-zinc-100";
  return (
    <div>
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className={`font-mono text-sm font-medium ${color}`}>{value}</div>
    </div>
  );
}
