import type { CoursePeriod, CourseResearch } from "@/lib/api";
import { Panel, Pill, minus } from "./ui";

function pct(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
}

function pts(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}`;
}

/** One period in a line: the option against no signal, trades, t, and the index. */
function Line({ label, p, strong }: { label: string; p: CoursePeriod | null; strong?: boolean }) {
  if (!p) return <div className="text-zinc-600">{label}: no trades</div>;
  return (
    <div className={strong ? "text-zinc-200" : "text-zinc-500"}>
      <span className={strong ? "text-zinc-400" : ""}>{label}</span>{" "}
      <span className="font-mono tabular-nums">{pct(p.mean_pct)} vs {pct(p.baseline_mean_pct)}</span>
      <span className="text-zinc-600"> · {p.num_trades} trades · t {minus(p.t_vs_baseline)} · index {pts(p.index_points_mean)} pts</span>
    </div>
  );
}

/** The user's own course strategies, tested the project's way. */
export function CourseResearchCard({ data }: { data: CourseResearch }) {
  const passed = data.rows.filter((r) => r.verdict !== "REJECTED").length;
  return (
    <Panel className="p-4">
      <p className="text-sm leading-relaxed text-zinc-300">
        Five strategies from your course notes, plus two versions of an idea one of them suggested. Every stop,
        target and undefined term was fixed before any run, and each is judged as a bought option against the same
        option bought at the same times with no signal. {passed} of {data.rows.length} pass.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="py-1.5 pr-3 font-medium">Strategy</th>
              <th className="py-1.5 pr-3 font-medium">Per trade vs no signal, by period</th>
              <th className="hidden py-1.5 pr-3 font-medium sm:table-cell">Judged on · t (bar)</th>
              <th className="py-1.5 font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const judged = r.periods[r.judged];
              return (
                <tr key={r.name} className="border-t border-zinc-800/70 align-top">
                  <td className="py-2 pr-3 text-zinc-200">
                    {r.label}
                    <div className="text-[10px] text-zinc-600">{r.timeframe} candles</div>
                  </td>
                  <td className="space-y-0.5 py-2 pr-3 text-[11px]">
                    {Object.entries(r.periods).map(([k, p]) => (
                      <Line key={k} label={k} p={p} strong={k === r.judged} />
                    ))}
                  </td>
                  <td className="hidden py-2 pr-3 font-mono tabular-nums text-zinc-400 sm:table-cell">
                    {r.judged} · {minus(judged?.t_vs_baseline ?? null)} ({minus(r.required_t)})
                  </td>
                  <td className="py-2" title={r.reason}>
                    <Pill tone={r.verdict === "APPROVED" ? "good" : r.verdict === "CONDITIONAL" ? "warn" : "bad"}>{r.verdict}</Pill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        Option returns are modelled: Black-Scholes on the real 5- and 15-minute index path with the previous session&apos;s
        volatility, the real expiry dates and this project&apos;s costs. The options archive keeps one price a day, so no
        intraday fill is measured. The course strategies are judged on 2024–26. The breakout pair came from the Trap&apos;s
        2024–26 result, so it is judged on 2015–17, which no study had used. Trap Trading is an adaptation of a EURUSD
        strategy. The bar is corrected for {data.tests_in_family} hypotheses. Plans fixed: {data.prereg.course}
        {data.prereg.breakout ? `, ${data.prereg.breakout}` : ""}.
      </p>
    </Panel>
  );
}
