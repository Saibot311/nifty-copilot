"use client";

import { useEffect, useState } from "react";
import type { LiveTick } from "@/lib/api";
import { subscribeToTick } from "@/lib/api";
import { fmtSigned } from "./ui";

const clock = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }) : null;

/** The header price, kept current while the market is open.
 *
 *  The dashboard is server-rendered once, so without this it shows the price
 *  from whenever the page was loaded. Polls every 2s while open, every 60s
 *  when shut, and never computes a number itself: change and percent come
 *  from Python.
 *
 *  It always says where the price came from and when that price was taken —
 *  not when the page last asked. The clock used to be the response time, so a
 *  frozen feed ticked on as "Live 14:32:10" with the price standing still. A
 *  price past its freshness is marked stale, and an unknown market status is
 *  said to be unknown rather than shown as "Closed". */
export function LiveTicker({ fallback }: { fallback: { price: number | null; change: number | null; changePct: number | null } }) {
  const [tick, setTick] = useState<LiveTick | null>(null);

  useEffect(() => subscribeToTick(setTick), []);

  const price = tick?.index ?? fallback.price;
  const change = tick ? tick.change ?? null : fallback.change;
  const changePct = tick ? tick.change_pct ?? null : fallback.changePct;
  const open = tick?.market?.is_open;
  const up = (change ?? 0) >= 0;
  const at = clock(tick?.quote_at ?? null);
  const stale = !!tick && (tick.stale || tick.offline);
  const source = !tick ? "as loaded" : tick.offline ? `${tick.source ?? "last price"} — connection lost`
    : tick.source ?? "unavailable";

  if (price == null) return <span className="text-sm text-zinc-500">backend offline</span>;

  return (
    <>
      <span className="font-mono text-2xl font-semibold tracking-tight text-zinc-50 tabular-nums">
        {price.toLocaleString("en-IN")}
      </span>
      <span className={`font-mono text-sm font-medium tabular-nums ${change == null ? "text-zinc-500" : up ? "text-emerald-400" : "text-rose-400"}`}>
        {change != null ? fmtSigned(change) : "–"}
        {changePct != null && ` (${fmtSigned(changePct)}%)`}
      </span>
      {tick && <span
        className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${
          open === true ? "text-emerald-400" : open === false ? "text-zinc-500" : "text-amber-300"}`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${open === true && !stale ? "animate-pulse bg-emerald-400" : open === true ? "bg-emerald-400" : open === false ? "bg-zinc-600" : "bg-amber-300"}`} />
        {open === true ? "Live" : open === false ? "Closed" : `Status unknown${tick?.market?.open_by_clock ? " — clock says open" : ""}`}
      </span>}
      <span className={`basis-full font-mono text-[10px] normal-case tracking-normal sm:basis-auto ${stale ? "text-amber-300" : "text-zinc-600"}`}>
        {source}{at ? ` · ${at} IST` : ""}{stale ? " · stale" : ""}
      </span>
    </>
  );
}
