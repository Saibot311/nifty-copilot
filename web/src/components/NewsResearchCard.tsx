import type { NewsResearch } from "@/lib/api";
import { Offline, Panel, Pill, minus } from "./ui";

/** The five pre-registered news-tone hypotheses and what the record says.
 *  Sits on Research, where verdicts live. */

const rs = (v: number | null | undefined) => {
  if (v == null) return "–";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
};

export function NewsResearchCard({ data }: { data: NewsResearch | null }) {
  if (!data) {
    return <Offline what="The news-tone study" why="It has not been run yet — the tone archive may still be filling." />;
  }
  if (!data.hypotheses?.length) {
    return (
      <Panel className="p-4 text-sm text-zinc-400">
        No verdict yet: the tone archive has {data.coverage?.days ?? 0} days and the study needs the whole
        2018–2026 span before it can judge anything.
      </Panel>
    );
  }

  const cov = data.coverage;
  return (
    <Panel className="p-4">
      <p className="text-sm leading-relaxed text-zinc-300">
        Five ideas about whether the <b>tone of news coverage</b> pays an option buyer, each tested as a bought
        call or put, with the rule fixed before any result existed. {data.approved} of {data.tested} beat buying
        the same option with no signal by more than luck.
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-600">
        Tone from GDELT, {cov?.days?.toLocaleString("en-IN")} days, {cov?.first} to {cov?.last}. A signal is read
        off a completed UTC day and entered at the next Indian session&apos;s close — a UTC day ends at 05:29 IST,
        before that session opens. Much of a day&apos;s market coverage is <i>about</i> that day&apos;s move, which is
        why that rule is not optional.
      </p>

      <div className="mt-3 flex flex-col gap-1.5">
        {data.hypotheses.map((h) => (
          <details key={h.name} className="rounded-lg bg-zinc-950/60 px-3 py-2">
            <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-200">
              <span className="min-w-[11rem] flex-1">{h.label}</span>
              <span className="text-[11px] text-zinc-500">{h.family}</span>
              <span className="font-mono text-xs tabular-nums text-zinc-300">
                {rs(h.holdout.avg_profit_per_lot_rs)}/lot vs {rs(h.holdout.baseline_avg_profit_per_lot_rs)}
                {h.holdout.ci_95 && (
                  <span className="block text-[10px] text-zinc-600">
                    could be {rs(h.holdout.ci_95.low)} to {rs(h.holdout.ci_95.high)}
                  </span>
                )}
              </span>
              <Pill tone={h.status === "APPROVED" ? "good" : h.status === "CONDITIONAL" ? "warn" : "bad"}>
                {h.status}
              </Pill>
            </summary>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              <span className="text-zinc-300">Rule: </span>{h.signal} Held {h.hold_sessions} session
              {h.hold_sessions > 1 ? "s" : ""}.
            </p>
            <p className="mt-1 text-xs leading-relaxed text-zinc-400">
              <span className="text-zinc-300">Why it might work: </span>{h.why}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-zinc-400">
              <span className="text-zinc-300">Record: </span>
              {h.signals_since_2018} signals since 2018 ({h.signals_per_year}/yr), {h.trades_taken} taken after the
              overlap rule. 2018–23: {h.development.num_trades ?? 0} trades,{" "}
              {rs(h.development.avg_profit_per_lot_rs)}/lot (no signal{" "}
              {rs(h.development.baseline_avg_profit_per_lot_rs)}). 2024–26: {h.holdout.num_trades ?? 0} trades,
              t = {minus(h.holdout.t)} against a bar of {minus(h.required_t)}.
            </p>
            <p className="mt-1 text-xs leading-relaxed text-zinc-300">{h.reason}</p>
          </details>
        ))}
      </div>

      {data.bar_note && (
        <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">{data.bar_note}</p>
      )}
      <p className="mt-1 font-mono text-[10px] text-zinc-600">
        pre-registration {data.prereg_hash} · query {data.query_set}
      </p>
    </Panel>
  );
}
