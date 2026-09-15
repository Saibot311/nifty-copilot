import type { ResearchCompareResult } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

export function ResearchCompare({ result }: { result: ResearchCompareResult | null }) {
  if (!result) return <Offline what="Strategy comparison" />;

  const rows = Object.entries(result.results).sort(
    (a, b) => (b[1].vs_baseline_pct ?? -999) - (a[1].vs_baseline_pct ?? -999)
  );
  const baseline = result.buy_and_hold_baseline;

  return (
    <Panel className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-xs text-zinc-500">
          {result.symbol} · {result.period.start} to {result.period.end} · {result.period.bars} daily bars ·
          identical costs &amp; {result.hold_days}-day hold for every strategy
        </div>
        <Pill tone="info">{result.total_hypotheses_tested_all_time} hypotheses logged</Pill>
      </div>

      {baseline && (
        <div className="mb-3 rounded-lg bg-zinc-950/60 px-3 py-2 text-[11px] leading-relaxed text-zinc-500">
          <span className="text-zinc-400">
            Buy-and-hold baseline: {baseline.expectancy_pct}% expectancy over {baseline.num_trades} re-entries.
          </span>{" "}
          {result.baseline_note}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
              <th className="pb-2 pr-3 font-medium">Strategy</th>
              <th className="pb-2 pr-3 text-center font-medium">Dir</th>
              <th className="pb-2 pr-3 text-right font-medium">Trades</th>
              <th className="pb-2 pr-3 text-right font-medium">Expectancy</th>
              <th className="pb-2 pr-3 text-right font-medium">vs. hold</th>
              <th className="pb-2 pr-3 text-right font-medium">PF</th>
              <th className="pb-2 text-right font-medium">Max DD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, m]) => {
              const positive = (m.expectancy_pct ?? 0) > 0;
              const beatsBaseline = (m.vs_baseline_pct ?? 0) > 0;
              const isCall = m.option_type === "CE";
              return (
                <tr key={name} className="border-t border-zinc-800/60">
                  <td className="py-1.5 pr-3 text-zinc-300">{m.label ?? name}</td>
                  <td className="py-1.5 pr-3 text-center">
                    <span className={`font-mono text-[10px] font-bold ${isCall ? "text-emerald-400" : "text-rose-400"}`}>
                      {m.option_type ?? "–"}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono text-zinc-400 tabular-nums">{m.num_trades}</td>
                  <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${positive ? "text-emerald-400" : "text-rose-400"}`}>
                    {m.expectancy_pct != null ? `${m.expectancy_pct > 0 ? "+" : ""}${m.expectancy_pct.toFixed(2)}%` : "–"}
                  </td>
                  <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${beatsBaseline ? "text-emerald-400" : "text-zinc-600"}`}>
                    {m.vs_baseline_pct != null ? `${m.vs_baseline_pct > 0 ? "+" : ""}${m.vs_baseline_pct.toFixed(2)}%` : "–"}
                  </td>
                  <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${(m.profit_factor ?? 0) >= 1 ? "text-emerald-400" : "text-rose-400"}`}>
                    {m.profit_factor != null ? m.profit_factor.toFixed(2) : "–"}
                  </td>
                  <td className="py-1.5 text-right font-mono text-rose-400 tabular-nums">
                    {m.max_drawdown_pct != null ? `${m.max_drawdown_pct.toFixed(1)}%` : "–"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
        Sorted by alpha over buy-and-hold, not raw expectancy — on a market with strong upward drift,
        raw expectancy flatters every long strategy and unfairly punishes every short one. Most rows
        here are legitimate exploratory dead ends, not failures. None of this is validated; see Phase 8.
      </p>
    </Panel>
  );
}
