import type { OptionsArchive, StrikeSweepResult } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

function cellStyle(expectancy: number | null, maxAbs: number) {
  if (expectancy == null) return { background: "rgba(113,113,122,0.12)", color: "#71717a" };
  const intensity = Math.min(Math.abs(expectancy) / maxAbs, 1);
  return expectancy >= 0
    ? { background: `rgba(52,211,153,${0.12 + intensity * 0.55})`, color: "#d1fae5" }
    : { background: `rgba(251,113,133,${0.12 + intensity * 0.55})`, color: "#ffe4e6" };
}

export function OptionsStrikeSweep({
  sweep,
  archive,
}: {
  sweep: StrikeSweepResult | null;
  archive: OptionsArchive | null;
}) {
  if (!sweep) return <Offline what="Options strike sweep" />;

  const offsets = [...new Set(sweep.grid.map((c) => c.strike_offset_pts))].sort((a, b) => a - b);
  const dtes = [...new Set(sweep.grid.map((c) => c.min_days_to_expiry))].sort((a, b) => a - b);
  const cellFor = (off: number, dte: number) =>
    sweep.grid.find((c) => c.strike_offset_pts === off && c.min_days_to_expiry === dte);
  const maxAbs = Math.max(...sweep.grid.map((c) => Math.abs(c.expectancy_pct ?? 0)), 0.01);

  const allNegative = sweep.combinations_with_positive_expectancy === 0 && sweep.combinations_with_trades > 0;

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-indigo-400">
          Which option should you actually buy?
        </div>
        <Pill tone={allNegative ? "bad" : "good"}>
          {sweep.combinations_with_positive_expectancy}/{sweep.combinations_with_trades} profitable
        </Pill>
      </div>
      <div className="text-xs text-zinc-500 mb-3">
        Returns on <span className="text-zinc-300">premium</span>, including theta decay and costs —
        not index returns. {sweep.signal_count} non-overlapping signals, {sweep.hold_days}-day hold.
      </div>

      {archive && (
        <div className="mb-3 rounded-lg bg-zinc-950/60 px-3 py-2 text-[11px] text-zinc-500">
          Options archive: {archive.option_bars.toLocaleString("en-IN")} rows ·{" "}
          {archive.trading_days_with_data} trading days · {archive.first_date} → {archive.last_date}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="border-separate" style={{ borderSpacing: 4 }}>
          <thead>
            <tr>
              <th className="whitespace-nowrap pr-2 text-right text-[11px] font-medium text-zinc-500">
                DTE ╲ strike
              </th>
              {offsets.map((off) => (
                <th key={off} className="px-1 pb-1 text-[11px] font-medium text-zinc-500">
                  {off === 0 ? "ATM" : off > 0 ? `+${off}` : `${off}`}
                  <div className="text-[9px] text-zinc-600">
                    {off === 0 ? "" : off > 0 ? "OTM" : "ITM"}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dtes.map((dte) => (
              <tr key={dte}>
                <td className="whitespace-nowrap pr-2 text-right text-[11px] font-medium text-zinc-500">
                  {dte}d
                </td>
                {offsets.map((off) => {
                  const cell = cellFor(off, dte);
                  const style = cellStyle(cell?.expectancy_pct ?? null, maxAbs);
                  return (
                    <td key={off}>
                      <div
                        className="min-w-[74px] rounded-md px-2 py-2 text-center font-mono text-xs"
                        style={style}
                        title={`${cell?.num_trades ?? 0} trades · win rate ${
                          cell?.win_rate != null ? Math.round(cell.win_rate * 100) + "%" : "n/a"
                        }`}
                      >
                        {cell?.expectancy_pct != null
                          ? `${cell.expectancy_pct > 0 ? "+" : ""}${cell.expectancy_pct.toFixed(1)}%`
                          : "–"}
                        <div className="text-[9px] opacity-70">{cell?.num_trades ?? 0}t</div>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {allNegative && (
        <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200/90">
          Every tested contract choice lost money on premium. A modest index edge doesn&apos;t
          automatically survive being expressed as a bought option — theta decay and spreads eat it.
          That&apos;s a finding, not a bug.
        </div>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
        {sweep.multiple_comparisons_note}
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">{sweep.cost_note}</p>
    </Panel>
  );
}
