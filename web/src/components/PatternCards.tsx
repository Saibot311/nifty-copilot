import type { OptionPeriodStats, PatternOptionsResearch, PatternToday, PatternsToday, SuggestedOption, Verdict } from "@/lib/api";
import { Offline, Panel, Pill, fmtPct, minus } from "./ui";

export const VERDICT_TONE: Record<Verdict, "good" | "warn" | "bad"> = {
  APPROVED: "good",
  CONDITIONAL: "warn",
  REJECTED: "bad",
};

function rupees(v: number | undefined) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN")}`;
}

export function OptionPill({ type }: { type: "CE" | "PE" }) {
  return <Pill tone={type === "CE" ? "good" : "bad"}>{type === "CE" ? "CALL" : "PUT"}</Pill>;
}

/** One line: what the suggested option did on data its choice never saw. */
export function TrackRecord({
  option,
  holdout,
  baselineRs,
  t,
  ci,
}: {
  option?: Pick<SuggestedOption, "description"> | null;
  holdout?: OptionPeriodStats | null;
  baselineRs?: number | null;
  t?: number | null;
  ci?: { low: number; high: number } | null;
}) {
  if (!option) return <p className="text-[11px] text-zinc-600">Too rare to test on options.</p>;
  return (
    <div className="space-y-0.5">
      <p className="text-xs text-zinc-300">{option.description}</p>
      {holdout && holdout.num_trades > 0 ? (
        <p className="font-mono text-[11px] tabular-nums text-zinc-500">
          2024–26: {holdout.num_trades} trades · win {holdout.win_rate != null ? `${(holdout.win_rate * 100).toFixed(0)}%` : "–"} · avg{" "}
          <span className={(holdout.avg_profit_per_lot_rs ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}>
            {rupees(holdout.avg_profit_per_lot_rs)}/lot
          </span>{" "}
          ({fmtPct(holdout.avg_return_pct, 1)}) · no signal {rupees(baselineRs ?? undefined)}/lot · t {minus(t)}
        </p>
      ) : (
        <p className="text-[11px] text-zinc-600">No trades in 2024–26 to judge it on.</p>
      )}
      {ci && (
        <p className="font-mono text-[11px] tabular-nums text-zinc-600">
          With so few trades, that average could as easily have been anywhere from {rupees(Math.round(ci.low))} to {rupees(Math.round(ci.high))} per lot.
        </p>
      )}
    </div>
  );
}

function Why({ p }: { p: { forms_when?: string; why?: string; reason?: string | null } }) {
  return (
    <details className="group mt-1.5">
      <summary className="cursor-pointer list-none text-[11px] text-indigo-300/80 hover:text-indigo-300">
        <span className="group-open:hidden">Why this pattern ▸</span>
        <span className="hidden group-open:inline">Why this pattern ▾</span>
      </summary>
      <div className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-zinc-400">
        {p.forms_when && <p><span className="text-zinc-500">Forms when: </span>{p.forms_when}</p>}
        {p.why && <p><span className="text-zinc-500">The idea: </span>{p.why}</p>}
        {p.reason && <p><span className="text-zinc-500">Verdict: </span>{p.reason}</p>}
      </div>
    </details>
  );
}

function levels(ranges: [number, number][]) {
  return ranges
    .map(([a, b]) => (a === b ? `near ${a.toLocaleString("en-IN")}` : `${a.toLocaleString("en-IN")}–${b.toLocaleString("en-IN")}`))
    .join(" or ");
}

function TodayRow({ p, lastClose }: { p: PatternToday; lastClose: number }) {
  const sure = p.trigger?.close_ranges_level ?? [];
  const maybe = p.trigger?.partial_ranges_level ?? [];
  return (
    <div className="rounded-lg bg-zinc-950/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <OptionPill type={p.option_type} />
          <span className="text-sm font-medium text-zinc-100">{p.label}</span>
        </div>
        <div className="flex items-center gap-2">
          {!p.formed_today && p.probability_next != null && (
            <span className="font-mono text-xs tabular-nums text-zinc-300">
              {(p.probability_next * 100).toFixed(0)}% of days
            </span>
          )}
          {p.status && <Pill tone={VERDICT_TONE[p.status]}>{p.status}</Pill>}
        </div>
      </div>
      {!p.formed_today && (sure.length > 0 || maybe.length > 0) && (
        <div className="mt-1.5 space-y-0.5 text-[11px] text-zinc-400">
          {sure.length > 0 && (
            <p>
              Forms if NIFTY closes {levels(sure)}
              {p.trigger?.needs.length ? <> with {p.trigger.needs.join(" and ")}</> : null}
            </p>
          )}
          {maybe.length > 0 && (
            <p className="text-zinc-500">
              {sure.length > 0 ? "Can also form" : "Can form"} at {levels(maybe)}, depending on the open and wicks
              {p.trigger?.needs.length && sure.length === 0 ? <> ({p.trigger.needs.join(" and ")})</> : null}
            </p>
          )}
          <p className="text-zinc-600">Last close {lastClose.toLocaleString("en-IN")}</p>
        </div>
      )}
      <div className="mt-2">
        <TrackRecord option={p.suggested_option} holdout={p.holdout} baselineRs={p.baseline?.holdout_avg_profit_per_lot_rs} t={p.holdout_t_stat} ci={p.holdout_ci_95} />
      </div>
      <Why p={p} />
    </div>
  );
}

export function PatternsTodayCard({ data }: { data: PatternsToday | null }) {
  if (!data) return <Offline what="Patterns" />;
  const formed = data.patterns.filter((p) => p.formed_today);
  const next = data.patterns.filter((p) => !p.formed_today && (p.probability_next ?? 0) >= 0.02);

  return (
    <Panel className="p-4">
      <p className="text-[11px] text-zinc-500">
        Judged from the close of {data.as_of} ({data.last_close.toLocaleString("en-IN")}).
      </p>

      <h3 className="mt-3 text-xs font-semibold text-zinc-300">Formed on that close</h3>
      <div className="mt-2 flex flex-col gap-2">
        {formed.length ? formed.map((p) => <TodayRow key={p.strategy} p={p} lastClose={data.last_close} />) : (
          <p className="text-xs text-zinc-600">None.</p>
        )}
      </div>

      <h3 className="mt-4 text-xs font-semibold text-zinc-300">Could form on the next close</h3>
      <div className="mt-2 flex flex-col gap-2">
        {next.length ? next.map((p) => <TodayRow key={p.strategy} p={p} lastClose={data.last_close} />) : (
          <p className="text-xs text-zinc-600">None within a typical day&apos;s move.</p>
        )}
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">{data.method_note}</p>
    </Panel>
  );
}

function ordinal(n: number) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

export function PatternOptionsTable({ data }: { data: PatternOptionsResearch | null }) {
  if (!data) return <Offline what="Pattern → option research" />;
  return (
    <Panel className="p-4">
      <p className="text-xs leading-relaxed text-zinc-400">{data.method_note}</p>
      <p className="mt-1 text-[11px] text-zinc-600">
        {data.configs_tested_total.toLocaleString("en-IN")} option setups tested · chosen on {data.options_period.start} –{" "}
        {data.options_period.split}, judged on {data.options_period.split} – {data.options_period.end}
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {data.patterns.map((p) => (
          <div key={p.strategy} className="rounded-lg bg-zinc-950/60 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <OptionPill type={p.option_type} />
                <span className="text-sm font-medium text-zinc-100">{p.label}</span>
                <span className="text-[11px] text-zinc-600">{p.forms_per_year}×/yr</span>
              </div>
              <Pill tone={VERDICT_TONE[p.status]}>{p.status}</Pill>
            </div>
            <div className="mt-2">
              <TrackRecord option={p.suggested_option} holdout={p.holdout} baselineRs={p.baseline?.holdout_avg_profit_per_lot_rs} t={p.holdout_t_stat} ci={p.holdout_ci_95} />
            </div>
            {p.iv?.median_entry_iv_pct != null && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-zinc-500">
                Options usually bought with implied volatility at the {ordinal(p.iv.median_entry_iv_pct)} percentile
                of the past year
                {p.iv.median_market_iv_change_pts != null &&
                  ` · market volatility moved ${p.iv.median_market_iv_change_pts >= 0 ? "+" : ""}${p.iv.median_market_iv_change_pts} pts over a typical hold`}
              </p>
            )}
            <Why p={p} />
          </div>
        ))}
      </div>
    </Panel>
  );
}
