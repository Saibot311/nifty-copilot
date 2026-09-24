import type { StrategyFit, StrategyFitRow } from "@/lib/api";
import { Offline, Panel, SectionLabel, fmtNum, minus } from "./ui";

/** Which strategies today's market suits.
 *
 *  Two different answers, side by side: whether each strategy is forming
 *  (Python, on real prices) and whether today is the kind of market its
 *  premise was written for (Jev). The record column is Python again — every
 *  one of these was rejected on 2024–26 data, and a fit is not a result. */

const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }) : null;

function forming(r: StrategyFitRow) {
  if (r.status === "forming now") return "would form if the index closed now";
  if (r.status === "formed") return "formed on the last close";
  const range = r.trigger_ranges[0];
  const where = range ? ` (closes ${fmtNum(range[0])}–${fmtNum(range[1])})` : "";
  if (r.status === "within reach") return `trigger ${minus(r.pct_to_trigger, 2)}% away${where}`;
  return `forms on ${Math.round(r.base_rate * 100)}% of days like this${where}`;
}

function FitBar({ fit }: { fit: number | null }) {
  if (fit == null) return <span className="text-[11px] text-zinc-600">unjudged</span>;
  return (
    <span className="flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800" aria-hidden>
        <span className="block h-full rounded-full bg-zinc-300" style={{ width: `${fit * 100}%` }} />
      </span>
      <span className="font-mono text-[12px] tabular-nums text-zinc-200">{fit.toFixed(2)}</span>
    </span>
  );
}

export function StrategyFitCard({ data }: { data: StrategyFit | null }) {
  if (!data) return <Offline what="Strategy fit" />;
  const m = data.market;
  const read = clock(data.judged_at);
  return (
    <Panel className="p-4">
      <p className="text-[12px] leading-relaxed text-zinc-400">
        Market as of {m.index.as_of}: {fmtNum(m.index.level)} ({minus(m.index.change_today_pct)}% on the day),{" "}
        {m.trend.classifier.replace("_", " ").toLowerCase()}, {minus(m.trend.return_20_sessions_pct)}% over 20
        sessions, RSI {minus(m.momentum.rsi_14)}, ADX {minus(m.momentum.adx_14)}, VIX {minus(m.volatility.india_vix)}.
      </p>
      {data.rows.length === 0 ? (
        <p className="mt-3 text-[12px] text-zinc-500">No strategy is forming or within reach of its trigger.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                <th className="py-2 pr-3 font-medium">Strategy</th>
                <th className="py-2 pr-3 font-medium">Forming? <span className="normal-case tracking-normal">(prices)</span></th>
                <th className="py-2 pr-3 font-medium">Fits today? <span className="normal-case tracking-normal">(Jev)</span></th>
                <th className="hidden py-2 font-medium sm:table-cell">2024–26 record</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.strategy} className="border-b border-zinc-800/50 align-top last:border-0">
                  <td className="py-2 pr-3">
                    <div className="text-zinc-200">{r.label}</div>
                    <div className="text-[11px] text-zinc-500">buys a {r.side} · {r.forms_when}</div>
                  </td>
                  <td className="py-2 pr-3 text-[12px] text-zinc-300">{forming(r)}</td>
                  <td className="py-2 pr-3"><FitBar fit={r.fit} /></td>
                  <td className="hidden py-2 font-mono text-[11px] tabular-nums text-zinc-500 sm:table-cell">
                    {r.evidence?.status ?? "–"}
                    {r.evidence?.t != null && <> · t {minus(r.evidence.t)} vs {minus(r.evidence.bar)}</>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">{data.caveat}</p>
      <p className="mt-1 text-[11px] text-zinc-600">
        {read ? `Read at ${read} IST by ${data.judged_by}.` : "Not read yet."}
        {data.note && ` ${data.note}.`} The number is the probability that today is the kind of market the
        premise describes — not a probability of the trade working.
      </p>
    </Panel>
  );
}

export function StrategyFitSection({ data }: { data: StrategyFit | null }) {
  return (
    <section className="min-w-0 xl:col-span-2">
      <SectionLabel hint="Jev's reading of the conditions — not a signal">Which strategies fit today</SectionLabel>
      <StrategyFitCard data={data} />
    </section>
  );
}
