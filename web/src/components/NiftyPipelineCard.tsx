import type { CoursePeriod, NiftyPipeline } from "@/lib/api";
import { Panel, Pill, fmtPct, minus } from "./ui";

/** One period in a line: the option against no signal, trades and t. */
function Line({ label, p, strong }: { label: string; p: CoursePeriod | null; strong?: boolean }) {
  if (!p) return <div className="text-zinc-600">{label}: no trades</div>;
  return (
    <div className={strong ? "text-zinc-200" : "text-zinc-500"}>
      <span className={strong ? "text-zinc-400" : ""}>{label}</span>{" "}
      <span className="font-mono tabular-nums">{fmtPct(p.mean_pct, 1)} vs {fmtPct(p.baseline_mean_pct, 1)}</span>
      <span className="text-zinc-600"> · {p.num_trades} trades · t {minus(p.t_vs_baseline)}</span>
    </div>
  );
}

function pts(v: number | null) {
  return v == null ? "–" : v.toFixed(1);
}

/** The strategy pipeline: which option to hold, then five rules fixed in advance and judged once. */
export function NiftyPipelineCard({ data }: { data: NiftyPipeline }) {
  const inst = data.instrument;
  const passed = data.rows.filter((r) => r.verdict === "APPROVED").length;
  const name = (e: string) => (e === "nearest" ? "the nearest expiry" : "the monthly");
  return (
    <Panel className="p-4">
      <p className="text-sm leading-relaxed text-zinc-300">
        Five rules drawn from published research and NIFTY&apos;s own calendar, each written down and fingerprinted
        before it was run, and judged once on 2024–26 as a bought option against the same option bought with no
        signal. {passed} of {data.rows.length} pass.
      </p>

      {inst && (
        <div className="mt-3 rounded-lg bg-zinc-950/60 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-zinc-500">
            First: which option to hold ({inst.period.from.slice(0, 4)}–{inst.period.to.slice(0, 4)}, no signal)
          </p>
          <table className="mt-2 w-full text-[11px]">
            <thead>
              <tr className="text-left text-[10px] text-zinc-500">
                <th className="py-1 pr-2 font-medium">At the money</th>
                <th className="py-1 pr-2 text-right font-medium">Held</th>
                <th className="py-1 pr-2 text-right font-medium">Points a session</th>
                <th className="py-1 text-right font-medium">Without slippage</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {inst.rows.map((r) => (
                <tr key={`${r.expiry}${r.hold}`} className="border-t border-zinc-800/60 text-zinc-400">
                  <td className="py-1 pr-2 font-sans">{r.expiry === "nearest" ? "Nearest expiry" : "Monthly"}</td>
                  <td className="py-1 pr-2 text-right">{r.hold}d</td>
                  <td className="py-1 pr-2 text-right text-zinc-200">{pts(r.carry_pts)}</td>
                  <td className="py-1 text-right">{pts(r.carry_pts_without_slippage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
            What one point of NIFTY exposure costs a buyer each session, in index points. With the assumed slippage (1.5%
            of premium a side) {name(inst.chosen.expiry)} is cheapest, and the rules below use it; without that
            assumption it is {name(inst.chosen_without_slippage.expiry)}. The real bid–ask spread decides between them,
            and the five-minute option snapshots now record it.
          </p>
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="py-1.5 pr-3 font-medium">Rule</th>
              <th className="py-1.5 pr-3 font-medium">Per trade vs no signal</th>
              <th className="hidden py-1.5 pr-3 font-medium sm:table-cell">t (bar)</th>
              <th className="py-1.5 font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.name} className="border-t border-zinc-800/70 align-top">
                <td className="py-2 pr-3 text-zinc-200">
                  {r.label}
                  <div className="text-[10px] text-zinc-600">{r.timeframe === "1d" ? "daily, real closes" : "5-minute, modelled option"}</div>
                  <details className="mt-1">
                    <summary className="cursor-pointer text-[10px] text-zinc-500 hover:text-zinc-400">the rule</summary>
                    <p className="mt-1 max-w-md text-[11px] leading-relaxed text-zinc-500">{r.rule}</p>
                  </details>
                </td>
                <td className="space-y-0.5 py-2 pr-3 text-[11px]">
                  {Object.entries(r.periods).map(([k, p]) => (
                    <Line key={k} label={k} p={p} strong={k === r.judged} />
                  ))}
                </td>
                <td className="hidden py-2 pr-3 font-mono tabular-nums text-zinc-400 sm:table-cell">
                  {minus(r.periods[r.judged]?.t_vs_baseline ?? null)} ({minus(r.required_t)})
                </td>
                <td className="py-2" title={r.reason}>
                  <Pill tone={r.verdict === "APPROVED" ? "good" : r.verdict === "CONDITIONAL" ? "warn" : "bad"}>{r.verdict}</Pill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        The two straddles are priced at NSE&apos;s real closing prices. The three intraday rules use a modelled option
        (Black-Scholes on the real 5-minute path, the previous session&apos;s volatility, real expiries and this
        project&apos;s costs); the Today tab now records them against real option prices. The bar is corrected for{" "}
        {data.tests_in_family} hypotheses. Plan fixed before the run: {data.prereg}.
      </p>
    </Panel>
  );
}
