"use client";

import { useEffect, useState } from "react";

import { type Indicators, get } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

// In a session the server folds today's candle so far into every reading;
// out of one, a slow check notices when the next session starts.
const LIVE_MS = 60_000;
const IDLE_MS = 300_000;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "11:05" for a moment in the session, "24 Sep" for a daily close. */
function when(asOf: string): string {
  if (asOf.includes("T")) return asOf.slice(11, 16);
  const [, m, d] = asOf.split("-").map(Number);
  return m && d ? `${d} ${MONTHS[m - 1]}` : asOf;
}

export function IndicatorGrid({ initial }: { initial: Indicators | null }) {
  const [data, setData] = useState(initial);
  const live = data?.live ?? false;

  useEffect(() => {
    const id = setInterval(async () => {
      if (document.visibilityState === "hidden") return;
      const res = await get<Indicators>("/api/indicators");
      if (res.data) setData(res.data);
    }, live ? LIVE_MS : IDLE_MS);
    return () => clearInterval(id);
  }, [live]);

  if (!data) return <Offline what="Indicators" />;

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/70 px-3 py-2">
        <span className="min-w-0 text-[11px] text-zinc-500">{data.basis}</span>
        {data.live && <Pill tone="warn">provisional</Pill>}
      </div>
      <div className="grid grid-cols-2">
        {data.tiles.map((t, i) => (
          <div
            key={t.key}
            className={`flex min-w-0 flex-col gap-0.5 p-3 ${i % 2 === 1 ? "border-l border-zinc-800/70" : ""} ${
              i >= 2 ? "border-t border-zinc-800/70" : ""
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-[11px] text-zinc-500">{t.name}</span>
              {/* Only a reading from another moment than the header's carries its own time. */}
              {t.as_of !== data.as_of && (
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-zinc-600">{when(t.as_of)}</span>
              )}
            </div>
            <span className="font-mono text-[13px] leading-snug tabular-nums text-zinc-100">{t.value}</span>
            {t.state && <span className="text-[11px] leading-snug text-zinc-400">{t.state}</span>}
            <span className="text-[10.5px] leading-snug text-zinc-500">{t.detail}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
