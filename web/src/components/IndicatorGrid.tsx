"use client";

import type { Indicators } from "@/lib/api";
import { Offline, Panel, Pill, SectionLabel } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "11:05" for a moment in the session, "24 Sep" for a daily close. */
function when(asOf: string): string {
  if (asOf.includes("T")) return asOf.slice(11, 16);
  const [, m, d] = asOf.split("-").map(Number);
  return m && d ? `${d} ${MONTHS[m - 1]}` : asOf;
}

/** In a session the server folds today's candle so far into every reading,
 *  and the page's AutoRefresh brings a new set each minute. No timer here
 *  (DESIGN §9): a card's own timer is how the open-interest card once froze. */
export function IndicatorGrid({ initial: data }: { initial: Indicators | null }) {
  const hint = data && (
    <>
      {data.basis}
      {data.live && <Pill tone="warn">provisional</Pill>}
    </>
  );

  return (
    <>
      <SectionLabel hint={hint}>Indicators</SectionLabel>
      {!data ? (
        <Offline what="Indicators" />
      ) : (
        // Columns follow the card's own width, not the window's: four where
        // there is room for four, two on a phone or a narrow column. Every
        // tile draws its top and left rule; the grid is pulled up and left by
        // a pixel so the outer ones fall under the panel's own border.
        <Panel className="@container overflow-hidden">
          <div className="-ml-px -mt-px grid grid-cols-2 @2xl:grid-cols-4">
            {data.tiles.map((t) => (
              <div key={t.key} className="flex min-w-0 flex-col border-l border-t border-zinc-800/70 px-3.5 py-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate text-[11px] text-zinc-500">{t.name}</span>
                  {/* Only a reading from another moment than the header's carries its own time. */}
                  {t.as_of !== data.as_of && (
                    <span className="shrink-0 font-mono text-[10px] tabular-nums text-zinc-600">{when(t.as_of)}</span>
                  )}
                </div>
                <span className="mt-1 font-mono text-sm font-medium leading-snug tabular-nums text-zinc-100">
                  {t.value}
                </span>
                <span className="text-[11px] leading-snug text-zinc-400">{t.state || " "}</span>
                <span className="mt-1.5 text-[10.5px] leading-snug text-zinc-500">{t.detail}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </>
  );
}
