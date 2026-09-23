"use client";

import { useEffect, useState } from "react";
import type { LiveTick } from "@/lib/api";
import { fetchTick } from "@/lib/api";

/** The header price, kept current while the market is open.
 *
 *  The dashboard is server-rendered once, so without this it shows the price
 *  from whenever the page was loaded — during a session that is wrong within
 *  a minute. Polls every 2s while open (Kite allows a quote a second and the
 *  backend caches for one), every 60s when shut, and never computes a number
 *  itself: change and percent come from Python. */
export function LiveTicker({ fallback }: { fallback: { price: number | null; change: number; changePct: number } }) {
  const [tick, setTick] = useState<LiveTick | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    const run = async () => {
      const r = await fetchTick();
      if (!alive) return;
      if (r.data) setTick(r.data);
      const open = r.data?.market?.is_open;
      timer = setTimeout(run, open ? 2000 : 60000);
    };
    run();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  const price = tick?.index ?? fallback.price;
  const change = tick?.change ?? fallback.change;
  const changePct = tick?.change_pct ?? fallback.changePct;
  const open = tick?.market?.is_open;
  const up = (change ?? 0) >= 0;
  const clock = tick ? new Date(tick.as_of).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }) : null;

  if (price == null) return <span className="text-sm text-zinc-500">backend offline</span>;

  return (
    <>
      <span className="font-mono text-2xl font-semibold tracking-tight text-zinc-50 tabular-nums">
        {price.toLocaleString("en-IN")}
      </span>
      <span className={`font-mono text-sm font-medium tabular-nums ${up ? "text-emerald-400" : "text-rose-400"}`}>
        {change != null ? `${up ? "+" : ""}${change.toFixed(2)}` : "–"}
        {changePct != null && ` (${up ? "+" : ""}${changePct.toFixed(2)}%)`}
      </span>
      <span
        className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${open ? "text-emerald-400" : "text-zinc-500"}`}
        title={tick?.source ? `${tick.source}${clock ? ` · ${clock} IST` : ""}` : undefined}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${open ? "animate-pulse bg-emerald-400" : "bg-zinc-600"}`} />
        {open ? "Live" : "Closed"}
        {open && clock && (
          <span className="font-mono normal-case tracking-normal text-zinc-600">{clock} IST</span>
        )}
      </span>
    </>
  );
}
