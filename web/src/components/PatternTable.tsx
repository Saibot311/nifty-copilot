"use client";

import { useMemo, useState } from "react";
import type { MeanCI, PatternOptionResult, PatternToday, Verdict } from "@/lib/api";
import { Pill } from "./ui";

/** One row of the table, whichever source it came from. */
export type PatternRow = {
  key: string;
  label: string;
  optionType: "CE" | "PE";
  status: Verdict | null;
  option: string | null;
  trades: number | null;
  winRate: number | null;
  avgRs: number | null;
  baselineRs: number | null;
  t: number | null;
  ci: MeanCI | null;
  when: string | null;
  formed: boolean;
  formsWhen?: string;
  idea?: string;
  reason?: string | null;
  note?: string | null;
};

const TONE: Record<Verdict, "good" | "warn" | "bad"> = { APPROVED: "good", CONDITIONAL: "warn", REJECTED: "bad" };

function rs(v: number | null | undefined, round = true) {
  if (v == null) return "–";
  const n = round ? Math.round(v) : v;
  return `${n >= 0 ? "+" : "−"}₹${Math.abs(n).toLocaleString("en-IN")}`;
}

function levels(ranges: [number, number][] | undefined) {
  if (!ranges?.length) return null;
  return ranges
    .map(([a, b]) => (a === b ? `near ${a.toLocaleString("en-IN")}` : `${a.toLocaleString("en-IN")}–${b.toLocaleString("en-IN")}`))
    .join(" or ");
}

function fromToday(p: PatternToday): PatternRow {
  const sure = levels(p.trigger?.close_ranges_level);
  return {
    key: p.strategy, label: p.label, optionType: p.option_type, status: p.status ?? null,
    option: p.suggested_option?.description ?? null,
    trades: p.holdout?.num_trades ?? null, winRate: p.holdout?.win_rate ?? null,
    avgRs: p.holdout?.avg_profit_per_lot_rs ?? null,
    baselineRs: p.baseline?.holdout_avg_profit_per_lot_rs ?? null,
    t: p.holdout_t_stat ?? null, ci: p.holdout_ci_95 ?? null,
    when: p.formed_today ? "Formed on the last close"
      : sure ? `Forms if NIFTY closes ${sure}`
      : p.probability_next != null ? `${Math.round(p.probability_next * 100)}% of recent days` : null,
    formed: !!p.formed_today, formsWhen: p.forms_when, idea: p.why, reason: p.reason ?? null,
    note: p.trigger?.needs?.length ? `Also needs ${p.trigger.needs.join(" and ")}.` : null,
  };
}

function fromResearch(p: PatternOptionResult): PatternRow {
  return {
    key: p.strategy, label: p.label, optionType: p.option_type, status: p.status,
    option: p.suggested_option?.description ?? null,
    trades: p.holdout?.num_trades ?? null, winRate: p.holdout?.win_rate ?? null,
    avgRs: p.holdout?.avg_profit_per_lot_rs ?? null,
    baselineRs: p.baseline?.holdout_avg_profit_per_lot_rs ?? null,
    t: p.holdout_t_stat ?? null, ci: p.holdout_ci_95 ?? null,
    when: `Forms about ${p.forms_per_year}× a year`, formed: false,
    formsWhen: p.forms_when, idea: p.why, reason: p.reason,
    note: p.iv?.median_entry_iv_pct != null
      ? `Usually bought with implied volatility at the ${p.iv.median_entry_iv_pct}th percentile of the past year.`
      : null,
  };
}

/** The 95% range, on one scale shared by every row, with zero marked.
 *  Seeing every interval straddle the zero line is the point. */
function RangeBar({ ci, lo, hi }: { ci: MeanCI | null; lo: number; hi: number }) {
  if (!ci) return <span className="text-[11px] text-zinc-700">not enough trades</span>;
  const W = 168, H = 18;
  const x = (v: number) => ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * W;
  const crossesZero = ci.low <= 0 && ci.high >= 0;
  const colour = crossesZero ? "#a1a1aa" : ci.low > 0 ? "#34d399" : "#fb7185";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
      aria-label={`95% range ${Math.round(ci.low)} to ${Math.round(ci.high)} rupees per lot, average ${Math.round(ci.mean)}`}>
      <title>{`Average ${rs(ci.mean)}/lot · 95% range ${rs(ci.low)} to ${rs(ci.high)} · ${ci.n} trades`}</title>
      <line x1={x(0)} x2={x(0)} y1="1" y2={H - 1} stroke="#3f3f46" strokeWidth="1" />
      <line x1={x(ci.low)} x2={x(ci.high)} y1={H / 2} y2={H / 2} stroke={colour} strokeWidth="3" strokeLinecap="round" />
      <circle cx={x(ci.mean)} cy={H / 2} r="4" fill={colour} stroke="#09090b" strokeWidth="1.5" />
    </svg>
  );
}

export function PatternTable({ today, research, caption }: {
  /** Mapping happens here, not in the page: the page is a server component. */
  today?: PatternToday[];
  research?: PatternOptionResult[];
  caption?: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(
    () => (today ? today.map(fromToday) : research ? research.map(fromResearch) : []),
    [today, research],
  );
  const [lo, hi] = useMemo(() => {
    const lows = rows.map((r) => r.ci?.low).filter((v): v is number => v != null);
    const highs = rows.map((r) => r.ci?.high).filter((v): v is number => v != null);
    if (!lows.length) return [-1, 1];
    // Clip the scale at the 10th/90th percentile of the ends, so one wild
    // interval doesn't squash every other row into a dot.
    const at = (xs: number[], q: number) => [...xs].sort((a, b) => a - b)[Math.floor(q * (xs.length - 1))];
    return [Math.min(at(lows, 0.1), 0), Math.max(at(highs, 0.9), 0)];
  }, [rows]);

  if (!rows.length) return <p className="text-xs text-zinc-600">None.</p>;

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800/80 bg-zinc-900/40">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-[0.12em] text-zinc-500">
            <th className="py-2 pl-4 pr-3 font-medium">Pattern</th>
            <th className="hidden py-2 pr-3 font-medium sm:table-cell">2024–26</th>
            <th className="py-2 pr-3 font-medium">Avg per lot</th>
            <th className="hidden py-2 pr-3 font-medium lg:table-cell">What it could really be</th>
            <th className="py-2 pr-4 text-right font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isOpen = open === r.key;
            return (
              <tr key={r.key} className="border-b border-zinc-800/60 last:border-0 align-top">
                <td colSpan={5} className="p-0">
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : r.key)}
                    aria-expanded={isOpen}
                    className="grid w-full grid-cols-[1fr_auto] items-center gap-x-3 px-4 py-2.5 text-left hover:bg-zinc-800/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 sm:grid-cols-[minmax(0,1fr)_7rem_7rem_10rem] lg:grid-cols-[minmax(0,1fr)_7rem_7rem_10rem_6rem]"
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${r.optionType === "CE" ? "bg-emerald-400" : "bg-rose-400"}`} />
                        <span className="truncate font-medium text-zinc-100">{r.label}</span>
                        {r.formed && <Pill tone="info">formed</Pill>}
                      </span>
                      {r.when && <span className="mt-0.5 block truncate text-[11px] text-zinc-500">{r.when}</span>}
                    </span>
                    <span className="hidden font-mono text-xs tabular-nums text-zinc-400 sm:block">
                      {r.trades != null ? `${r.trades} trades` : "—"}
                      {r.winRate != null && <span className="block text-[10px] text-zinc-600">won {Math.round(r.winRate * 100)}%</span>}
                    </span>
                    <span className={`font-mono text-xs tabular-nums ${(r.avgRs ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {rs(r.avgRs)}
                      <span className="block text-[10px] text-zinc-600">no signal {rs(r.baselineRs)}</span>
                    </span>
                    <span className="hidden lg:block"><RangeBar ci={r.ci} lo={lo} hi={hi} /></span>
                    <span className="justify-self-end">{r.status && <Pill tone={TONE[r.status]}>{r.status}</Pill>}</span>
                  </button>
                  {isOpen && (
                    <div className="grid gap-1.5 border-t border-zinc-800/60 bg-zinc-950/50 px-4 py-3 text-[12px] leading-relaxed text-zinc-400">
                      {r.option && <p><span className="text-zinc-500">The option tested: </span>{r.option}</p>}
                      {r.formsWhen && <p><span className="text-zinc-500">Forms when: </span>{r.formsWhen}</p>}
                      {r.idea && <p><span className="text-zinc-500">The idea: </span>{r.idea}</p>}
                      {r.ci && (
                        <p><span className="text-zinc-500">How sure: </span>
                          the average was {rs(r.ci.mean)} per lot over {r.ci.n} trades, but with that few it could
                          as easily have been anywhere from {rs(r.ci.low)} to {rs(r.ci.high)}
                          {r.t != null && <> (t = {r.t})</>}.
                        </p>
                      )}
                      {r.note && <p className="text-zinc-500">{r.note}</p>}
                      {r.reason && <p><span className="text-zinc-500">Verdict: </span>{r.reason}</p>}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="border-t border-zinc-800/60 px-4 py-2 text-[11px] text-zinc-600">
        <div className="hidden lg:grid lg:grid-cols-[minmax(0,1fr)_7rem_7rem_10rem_6rem] lg:items-center lg:gap-x-3">
          <span className="col-start-4">
            {/* the shared scale the bars are drawn on, stated once */}
            <span className="flex justify-between font-mono text-[10px] tabular-nums text-zinc-600" style={{ width: 168 }}>
              <span>{rs(lo)}</span><span>₹0</span><span>{rs(hi)}</span>
            </span>
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="hidden lg:inline">
            <span className="mr-1.5 inline-block h-[3px] w-6 rounded-full align-middle" style={{ background: "#a1a1aa" }} />
            a range touching ₹0 means the edge could be nothing
          </span>
          <span>Click a row for the detail.</span>
          {caption && <span>{caption}</span>}
        </div>
      </div>
    </div>
  );
}
