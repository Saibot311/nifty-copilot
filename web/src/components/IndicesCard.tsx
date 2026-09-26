"use client";

import { useEffect, useState } from "react";

import { type IndexRow, type IndicesBoard, subscribeToTick } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "11:05" today, "25 Sep 15:30" for an earlier day. */
function when(asOf: string | null, now: string): string {
  if (!asOf) return "time unknown";
  const hm = asOf.slice(11, 16);
  if (asOf.slice(0, 10) === now.slice(0, 10)) return hm;
  const [, m, d] = asOf.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${hm}`;
}

/** Where the price sits between the day's low and high. */
function DayRange({ r }: { r: IndexRow }) {
  if (r.day_position == null || r.low == null || r.high == null) return null;
  return (
    <div className="flex items-center gap-2" title={`${r.day_position}% of the way from the day's low to its high`}>
      <span className="hidden font-mono text-[10px] tabular-nums text-zinc-600 sm:inline">
        {r.low.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
      </span>
      <div className="relative h-1 w-16 rounded-full bg-zinc-800 sm:w-24">
        <div className="absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 rounded-full bg-zinc-300"
             style={{ left: `calc(${r.day_position}% - 1px)` }} />
      </div>
      <span className="hidden font-mono text-[10px] tabular-nums text-zinc-600 sm:inline">
        {r.high.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
      </span>
    </div>
  );
}

/** NIFTY, Bank Nifty, Sensex and GIFT Nifty, from the shared live tick
 *  (every 2s in a session, every 60s outside it) — no timer of its own. */
export function IndicesCard({ initial }: { initial: IndicesBoard | null }) {
  const [live, setLive] = useState<IndicesBoard | null>(null);
  useEffect(() => subscribeToTick((t) => { if (t.indices) setLive(t.indices); }), []);
  const data = live ?? initial;

  if (!data || data.rows.length === 0) return <Offline what="The indices board" why="None of its feeds answered." />;

  return (
    <Panel>
      <div className="divide-y divide-zinc-800/70">
        {data.rows.map((r) => (
          <div key={r.key} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5">
            <div className="flex min-w-0 items-baseline gap-3">
              <span className="w-20 shrink-0 text-[13px] text-zinc-300">{r.name}</span>
              <span className="font-mono text-[15px] font-medium tabular-nums text-zinc-100">
                {r.last.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              {/* The sign carries the direction. Emerald and rose mean money made
                  and lost (DESIGN §2), and an index rising is neither to a put buyer. */}
              <span className="font-mono text-[12px] tabular-nums text-zinc-400">
                {r.change_text}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <DayRange r={r} />
              <span className="w-24 text-right font-mono text-[10px] tabular-nums text-zinc-600" title={r.source}>
                {when(r.as_of, data.as_of)}
              </span>
              {r.behind && <Pill tone="warn">behind</Pill>}
            </div>
          </div>
        ))}
      </div>
      <ul className="flex flex-col gap-1.5 border-t border-zinc-800/70 px-4 py-3">
        {data.commentary.map((line) => (
          <li key={line} className="text-[12px] leading-relaxed text-zinc-400">{line}</li>
        ))}
      </ul>
      <p className="border-t border-zinc-800/70 px-4 py-2.5 text-[11px] leading-relaxed text-zinc-600">
        NIFTY and Bank Nifty from NSE, Sensex from Yahoo&apos;s one-minute bars (BSE refuses outside requests),
        GIFT Nifty from NSE IX. GIFT Nifty is a USD-settled future trading about 21 hours a day at a premium to
        the index, so compare its change, not its level.
      </p>
    </Panel>
  );
}
