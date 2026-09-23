"use client";

import { useState } from "react";
import type { PlaybookEntry } from "@/lib/api";
import { Offline, Panel, Pill, fmtPct } from "./ui";

const TONE: Record<string, "good" | "warn" | "bad"> = {
  APPROVED: "good",
  CONDITIONAL: "warn",
  REJECTED: "bad",
};

/** Twenty-six verdicts. As stacked cards this ran to 2,666px and repeated a
 *  timestamp on every row — DESIGN.md §3 and the first anti-pattern in §10.
 *  One row each, the reason behind a click, and a single "as of" above. */
export function PlaybookCard({ entries }: { entries: PlaybookEntry[] | null }) {
  const [open, setOpen] = useState<string | null>(null);

  if (!entries) return <Offline what="The strategy playbook" />;
  if (entries.length === 0) {
    return (
      <Panel className="p-4 text-sm text-zinc-500">
        No strategy has been through walk-forward validation yet.
      </Panel>
    );
  }

  const order: Record<string, number> = { APPROVED: 0, CONDITIONAL: 1, REJECTED: 2 };
  const rows = [...entries].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
  const checked = rows
    .map((e) => e.checked_at)
    .sort()
    .slice(-1)[0];

  return (
    <div className="measure overflow-hidden rounded-xl border border-zinc-800/80 bg-zinc-900/40">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-zinc-800 px-4 py-2 text-[11px] text-zinc-500">
        <span>
          Every strategy that has been through walk-forward validation on index returns — a stored
          record, not a live recomputation.
        </span>
        <span className="font-mono tabular-nums">
          {rows.length} checked · last {checked?.slice(0, 10) ?? "—"}
        </span>
      </div>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-[0.12em] text-zinc-500">
            <th className="py-2 pl-4 pr-3 font-medium">Strategy</th>
            <th className="hidden py-2 pr-3 font-medium sm:table-cell">Trades</th>
            <th className="py-2 pr-3 font-medium">Per trade</th>
            <th className="py-2 pr-4 text-right font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const isOpen = open === e.strategy;
            return (
              <tr key={e.strategy} className="border-b border-zinc-800/60 last:border-0 align-top">
                <td colSpan={4} className="p-0">
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : e.strategy)}
                    aria-expanded={isOpen}
                    className="grid w-full grid-cols-[minmax(0,1fr)_5rem_5rem] items-center gap-x-3 px-4 py-2 text-left hover:bg-zinc-800/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 sm:grid-cols-[minmax(0,1fr)_5rem_6rem_6rem]"
                  >
                    <span className="truncate text-zinc-200">{e.label}</span>
                    <span className="hidden font-mono text-xs tabular-nums text-zinc-500 sm:block">
                      {e.num_trades ?? "—"}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-zinc-400">
                      {e.expectancy_pct != null ? fmtPct(e.expectancy_pct) : "–"}
                    </span>
                    <span className="justify-self-end">
                      <Pill tone={TONE[e.status] ?? "warn"}>{e.status}</Pill>
                    </span>
                  </button>
                  {isOpen && (
                    <div className="border-t border-zinc-800/60 bg-zinc-950/50 px-4 py-3 text-[12px] leading-relaxed text-zinc-400">
                      <p>{e.reason}</p>
                      <p className="mt-1 font-mono text-[11px] text-zinc-600">
                        checked {e.checked_at.slice(0, 10)}
                        {e.num_trades != null && ` · ${e.num_trades} trades`}
                      </p>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
