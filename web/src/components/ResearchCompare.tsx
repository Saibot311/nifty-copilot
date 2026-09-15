import type { ResearchCompareResult } from "@/lib/api";
import { Offline, Panel, Pill, fmtPct } from "./ui";

const NAME_LABEL: Record<string, string> = {
  ema_pullback: "EMA Pullback",
  rsi_reversal: "RSI Oversold Reversal",
  prev_day_breakout: "Prev-Day-High Breakout",
  bollinger_reversion: "Bollinger Band Reversion",
};

export function ResearchCompare({ result }: { result: ResearchCompareResult | null }) {
  if (!result) return <Offline what="Strategy comparison" />;

  const rows = Object.entries(result.results).sort(
    (a, b) => (b[1].expectancy_pct ?? -Infinity) - (a[1].expectancy_pct ?? -Infinity)
  );

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <div className="text-xs text-zinc-500">
          {result.symbol} · {result.period.start} to {result.period.end} · {result.period.bars} daily bars ·
          identical costs &amp; {result.hold_days}-day hold for every strategy
        </div>
        <Pill tone="info">{result.total_hypotheses_tested_all_time} hypotheses logged</Pill>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
              <th className="pb-2 pr-3 font-medium">Strategy</th>
              <th className="pb-2 pr-3 font-medium text-right">Trades</th>
              <th className="pb-2 pr-3 font-medium text-right">Expectancy</th>
              <th className="pb-2 pr-3 font-medium text-right">Profit Factor</th>
              <th className="pb-2 font-medium text-right">Max Drawdown</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, m]) => {
              const positive = (m.expectancy_pct ?? 0) > 0;
              return (
                <tr key={name} className="border-t border-zinc-800/80">
                  <td className="py-2 pr-3 font-medium text-zinc-200">{NAME_LABEL[name] ?? name}</td>
                  <td className="py-2 pr-3 text-right font-mono text-zinc-300">{m.num_trades}</td>
                  <td className={`py-2 pr-3 text-right font-mono ${positive ? "text-emerald-400" : "text-rose-400"}`}>
                    {m.expectancy_pct != null ? `${m.expectancy_pct > 0 ? "+" : ""}${m.expectancy_pct.toFixed(2)}%` : "n/a"}
                  </td>
                  <td className={`py-2 pr-3 text-right font-mono ${(m.profit_factor ?? 0) >= 1 ? "text-emerald-400" : "text-rose-400"}`}>
                    {m.profit_factor != null ? m.profit_factor.toFixed(2) : "n/a"}
                  </td>
                  <td className="py-2 text-right font-mono text-rose-400">
                    {m.max_drawdown_pct != null ? `${m.max_drawdown_pct.toFixed(1)}%` : "n/a"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-zinc-600">
        Only the top strategy here is worth carrying forward — the rest are legitimate exploratory dead ends,
        not failures. None of this is validated yet; see Phase 8.
      </p>
    </Panel>
  );
}