import type { Similarity } from "@/lib/api";
import { Offline, Panel, Pill, fmtPct, minus } from "./ui";

function rupees(v: number | null) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN")}`;
}

export function SimilarityCard({ data }: { data: Similarity | null }) {
  if (!data) return <Offline what="Similar past days" />;
  const wf = data.walk_forward;
  // Decided in Python with the verdict, not re-judged here (I2).
  const predictive = wf.predictive === true;
  const a = data.outcomes.analogs;
  const b = data.outcomes.all_days;
  const opt = data.options_on_analog_days;

  return (
    <Panel className="p-4">
      <div className={`rounded-lg px-3 py-2 text-xs leading-relaxed ${predictive ? "bg-emerald-500/10 text-emerald-200" : "bg-amber-500/10 text-amber-200/90"}`}>
        <span className="font-semibold">{predictive ? "Has predicted well. " : "Context, not a forecast. "}</span>
        {wf.verdict}{" "}
        {wf.rank_correlation != null && (
          <span className="text-zinc-400">
            (walk-forward since {wf.period_start?.slice(0, 4)}: {wf.test_points} tests, correlation {wf.rank_correlation}, t{" "}
            {minus(wf.t_stat)}, direction right {wf.direction_hit_rate != null ? `${(wf.direction_hit_rate * 100).toFixed(0)}%` : "–"} of the time)
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {Object.entries(data.today).map(([k, v]) => (
          <div key={k} className="rounded-lg bg-zinc-950/60 px-2.5 py-2">
            <div className="truncate text-[10px] text-zinc-500">{data.feature_labels[k]}</div>
            <div className="font-mono text-sm tabular-nums text-zinc-100">{typeof v === "number" ? minus(v) : v}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
            <tr>
              <th className="pb-1.5 font-medium">After</th>
              <th className="pb-1.5 font-medium">{data.analogs.length} similar days</th>
              <th className="pb-1.5 font-medium">All past days</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums text-zinc-300">
            {(["1d", "5d", "10d"] as const).map((h) => (
              <tr key={h} className="border-t border-zinc-800/60">
                <td className="py-1.5 text-zinc-500">{h.replace("d", " day" + (h === "1d" ? "" : "s"))}</td>
                <td className="py-1.5">
                  {(a[h].pct_higher * 100).toFixed(0)}% higher · median {fmtPct(a[h].median_pct)}
                </td>
                <td className="py-1.5 text-zinc-500">
                  {(b[h].pct_higher * 100).toFixed(0)}% higher · median {fmtPct(b[h].median_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {opt && (
        <p className="mt-3 text-[11px] leading-relaxed text-zinc-400">
          On the similar days since 2018, buying an {opt.option.split(",")[0]} option for {opt.hold_days} days made:{" "}
          <span className="text-zinc-300">CALL {rupees(opt.CE.avg_profit_per_lot_rs)}/lot</span> (won{" "}
          {opt.CE.win_rate != null ? `${(opt.CE.win_rate * 100).toFixed(0)}%` : "–"} of {opt.CE.trades}),{" "}
          <span className="text-zinc-300">PUT {rupees(opt.PE.avg_profit_per_lot_rs)}/lot</span> (won{" "}
          {opt.PE.win_rate != null ? `${(opt.PE.win_rate * 100).toFixed(0)}%` : "–"} of {opt.PE.trades}).
        </p>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] text-indigo-300/80 hover:text-indigo-300">
          The {data.analogs.length} similar days ▸
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
              <tr>
                <th className="pb-1 font-medium">Date</th>
                <th className="pb-1 text-right font-medium">Distance</th>
                <th className="pb-1 text-right font-medium">Next 5d</th>
                <th className="pb-1 text-right font-medium">Next 10d</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums text-zinc-300">
              {data.analogs.map((r) => (
                <tr key={r.date} className="border-t border-zinc-800/60">
                  <td className="py-1">{r.date}</td>
                  <td className="py-1 text-right text-zinc-500">{r.distance}</td>
                  <td className={`py-1 text-right ${r.fwd_5d >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fmtPct(r.fwd_5d)}</td>
                  <td className={`py-1 text-right ${r.fwd_10d >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fmtPct(r.fwd_10d)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
        {data.method_note} <Pill tone="neutral">as of {data.as_of}</Pill>
      </p>
    </Panel>
  );
}
