import type { Replication } from "@/lib/api";
import { Panel, Pill } from "./ui";

const INDEX_LABEL: Record<string, string> = { NIFTY: "NIFTY", BANKNIFTY: "Bank", MIDCPNIFTY: "Midcap", SENSEX: "Sensex" };

function pct(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
}

export function ReplicationCard({ data }: { data: Replication }) {
  const indices = Object.keys(data.coverage);
  const passed = data.hypotheses.filter((h) => h.status !== "REJECTED").length;
  // Sorted by the edge the API computed, not by one worked out here.
  const rows = [...data.hypotheses].sort((a, b) => b.pooled.holdout_edge_pct - a.pooled.holdout_edge_pct);
  return (
    <Panel className="p-4">
      <p className="text-sm leading-relaxed text-zinc-300">
        The same rules and the same option setups, run on {indices.map((u) => INDEX_LABEL[u] ?? u).join(", ")} to give each
        verdict more trades without adding new ideas. Indices move together, so a date counts once. {passed} of{" "}
        {data.hypotheses.length} pass on the pooled 2024–26 data.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="py-1.5 pr-3 font-medium">Idea</th>
              <th className="py-1.5 pr-3 font-medium">Pooled 2024–26 vs no signal</th>
              <th className="py-1.5 pr-3 font-medium">Dates</th>
              <th className="py-1.5 pr-3 font-medium">t (bar)</th>
              {indices.map((u) => <th key={u} className="py-1.5 pr-3 font-medium">{INDEX_LABEL[u] ?? u}</th>)}
              <th className="py-1.5 font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.name} className="border-t border-zinc-800/70 align-top">
                <td className="py-1.5 pr-3 text-zinc-200">{h.label}<div className="text-[10px] text-zinc-600">{h.setup}</div></td>
                <td className="py-1.5 pr-3 font-mono tabular-nums text-zinc-300">
                  {pct(h.pooled.holdout_avg_pct)} vs {pct(h.pooled.baseline_holdout_avg_pct)}
                  {h.pooled.holdout_ci_95 && (
                    <div className="text-[10px] text-zinc-600">could be {pct(h.pooled.holdout_ci_95.low)} to {pct(h.pooled.holdout_ci_95.high)}</div>
                  )}
                </td>
                <td className="py-1.5 pr-3 font-mono tabular-nums text-zinc-400">{h.pooled.holdout_dates}</td>
                <td className="py-1.5 pr-3 font-mono tabular-nums text-zinc-400">{h.pooled.holdout_t ?? "–"} ({h.pooled.required_t ?? "–"})</td>
                {indices.map((u) => {
                  const x = h.per_index[u];
                  const edge = x?.holdout_edge_pct ?? null;
                  return (
                    <td key={u} className={`py-1.5 pr-3 font-mono tabular-nums ${edge == null ? "text-zinc-600" : edge > 0 ? "text-emerald-300" : "text-rose-300"}`}
                      title={x ? `${x.holdout.trades} trades, avg ${pct(x.holdout.avg_return_pct)} vs no signal ${pct(x.baseline_holdout_avg_pct)}` : ""}>
                      {edge == null ? "–" : pct(edge)}
                    </td>
                  );
                })}
                <td className="py-1.5"><Pill tone={h.status === "APPROVED" ? "good" : h.status === "CONDITIONAL" ? "warn" : "bad"}>{h.status}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        Per-index columns: each index&apos;s 2024–26 edge over buying the same option with no signal, in return on premium.
        {" "}A &quot;could be&quot; range is the 95% bootstrap interval — where the average would land if these
        same trades had come out differently. {data.measure} The bar is corrected for {data.tests_counted} looks at the 2024–26 data. Plan fixed {data.registered}.
      </p>
    </Panel>
  );
}
