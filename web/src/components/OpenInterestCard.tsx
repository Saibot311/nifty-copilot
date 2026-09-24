"use client";

import { useEffect, useState } from "react";
import type { OptionChain } from "@/lib/api";
import { fetchOptionsChain } from "@/lib/api";
import { Offline, Panel } from "./ui";

/** Where open interest sits across strikes, from NSE's live chain.
 *
 *  Puts run left, calls run right, from a strike axis down the middle. Side
 *  is encoded by POSITION, not by colour: DESIGN.md §2 reserves emerald for
 *  money made and rose for money lost, and a call is neither. Using them
 *  here would say "calls good, puts bad", which is not what open interest
 *  means and not something anyone has shown.
 *
 *  The level says where positions already sit. The change says where they
 *  were opened today, which is the part that is actually news — so both are
 *  on the row, the level as the bar and the change as the figure.
 */

const fmtOi = (v: number) => {
  const lakh = v / 100_000;
  if (Math.abs(lakh) >= 1) return `${lakh.toFixed(1)}L`;
  const k = v / 1000;
  return Math.abs(k) >= 1 ? `${k.toFixed(0)}k` : `${Math.round(v)}`;
};

const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtOi(Math.abs(v))}`;

function Row({ r, max, spot, peakPut, peakCall }: {
  r: OptionChain["open_interest"]["ladder"][number]; max: number; spot: number;
  peakPut: number | null; peakCall: number | null;
}) {
  const putPct = max ? (r.put_oi / max) * 100 : 0;
  const callPct = max ? (r.call_oi / max) * 100 : 0;
  const nearSpot = Math.abs(r.strike - spot) < 25;
  const isPeakPut = r.strike === peakPut;
  const isPeakCall = r.strike === peakCall;

  return (
    <div className={`grid grid-cols-[1fr_4.5rem_1fr] items-center gap-1.5 py-[3px] ${nearSpot ? "bg-zinc-800/40" : ""}`}>
      {/* puts, growing leftwards */}
      <div className="flex items-center justify-end gap-1.5">
        <span className="hidden font-mono text-[10px] tabular-nums text-zinc-600 sm:inline">
          {r.put_oi_change !== 0 && signed(r.put_oi_change)}
        </span>
        <div className="h-3 w-full max-w-[9rem] overflow-hidden rounded-[2px] bg-zinc-900/60">
          <div className={`ml-auto h-full rounded-[2px] ${isPeakPut ? "bg-zinc-200" : "bg-zinc-400/70"}`}
               style={{ width: `${putPct}%` }} title={`${r.put_oi.toLocaleString("en-IN")} put OI at ${r.strike}`} />
        </div>
      </div>

      <div className={`text-center font-mono text-[11px] tabular-nums ${
        r.is_atm ? "font-semibold text-zinc-100" : nearSpot ? "text-zinc-300" : "text-zinc-500"}`}>
        {r.strike.toLocaleString("en-IN")}
      </div>

      {/* calls, growing rightwards */}
      <div className="flex items-center gap-1.5">
        <div className="h-3 w-full max-w-[9rem] overflow-hidden rounded-[2px] bg-zinc-900/60">
          <div className={`h-full rounded-[2px] ${isPeakCall ? "bg-zinc-200" : "bg-zinc-500/70"}`}
               style={{ width: `${callPct}%` }} title={`${r.call_oi.toLocaleString("en-IN")} call OI at ${r.strike}`} />
        </div>
        <span className="hidden font-mono text-[10px] tabular-nums text-zinc-600 sm:inline">
          {r.call_oi_change !== 0 && signed(r.call_oi_change)}
        </span>
      </div>
    </div>
  );
}

export function OpenInterestCard({ initial }: { initial?: OptionChain | null }) {
  const [data, setData] = useState<OptionChain | null>(initial ?? null);

  useEffect(() => {
    let alive = true;
    const pull = () => fetchOptionsChain().then((r) => { if (alive && r.data) setData(r.data); });
    if (!initial) pull();
    const id = setInterval(pull, 120_000);
    return () => { alive = false; clearInterval(id); };
  }, [initial]);

  if (!data) return <Offline what="The open-interest profile" why="NSE's option chain did not answer." />;

  const oi = data.open_interest;
  const ladder = oi.ladder ?? [];
  if (ladder.length === 0) return <Offline what="The open-interest profile" why="NSE returned no strikes for this expiry." />;
  const max = Math.max(...ladder.flatMap((r) => [r.call_oi, r.put_oi]), 1);

  return (
    <Panel className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-[13px] text-zinc-300">
          Where open interest sits for the {data.expiry} expiry.
        </span>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          NSE {data.as_of || "—"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Put/call OI</div>
          <div className="font-mono text-lg tabular-nums text-zinc-100">{oi.pcr ?? "–"}</div>
          <div className="text-[10px] text-zinc-600">{fmtOi(oi.total_put)} puts / {fmtOi(oi.total_call)} calls</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Most puts</div>
          <div className="font-mono text-lg tabular-nums text-zinc-100">
            {oi.max_put_oi_strike?.toLocaleString("en-IN") ?? "–"}
          </div>
          <div className="text-[10px] text-zinc-600">read as support — untested here</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Most calls</div>
          <div className="font-mono text-lg tabular-nums text-zinc-100">
            {oi.max_call_oi_strike?.toLocaleString("en-IN") ?? "–"}
          </div>
          <div className="text-[10px] text-zinc-600">read as resistance — untested here</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Opened today</div>
          <div className="font-mono text-sm tabular-nums text-zinc-300">
            {signed(oi.put_oi_added ?? 0)} puts
          </div>
          <div className="font-mono text-sm tabular-nums text-zinc-300">
            {signed(oi.call_oi_added ?? 0)} calls
          </div>
        </div>
      </div>

      <div className="mt-4">
        <div className="grid grid-cols-[1fr_4.5rem_1fr] gap-1.5 border-b border-zinc-800 pb-1 text-[10px] uppercase tracking-[0.1em] text-zinc-500">
          <span className="text-right">Puts</span>
          <span className="text-center">Strike</span>
          <span>Calls</span>
        </div>
        <div className="mt-1">
          {ladder.map((r) => (
            <Row key={r.strike} r={r} max={max} spot={data.underlying_value}
                 peakPut={oi.max_put_oi_strike} peakCall={oi.max_call_oi_strike} />
          ))}
        </div>
        <p className="mt-2 text-[10px] text-zinc-600">
          Bar length is open interest, on one scale shared by both sides. On a wider screen the figure beside
          each bar is how much was opened or closed today. The shaded row is the strike nearest the {data.underlying_value.toLocaleString("en-IN")} spot;
          the two brightest bars are the heaviest strikes named above.
          {oi.peaks_shown === false && " One of those strikes sits outside this range and is not drawn."}
        </p>
      </div>

      <p className="mt-3 border-t border-zinc-800 pt-2 text-[11px] leading-relaxed text-zinc-500">
        {data.interpretation_caveat}
      </p>
      {data.notes?.length > 0 && (
        <p className="mt-1 text-[11px] text-amber-200/80">{data.notes.join(" ")}</p>
      )}
    </Panel>
  );
}
