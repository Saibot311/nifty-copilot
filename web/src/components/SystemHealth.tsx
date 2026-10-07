"use client";

import { useState } from "react";
import type { Incident, Sentinel } from "@/lib/api";

/** One line under the freshness line: the sentinel's verdict (api/sentinel/).
 *  "All checks passing", or how many incidents are open with the oldest named;
 *  a button opens each one — when it opened, how often it was seen, every
 *  repair tried and its result. Amber for a warning, rose only for critical,
 *  and the word always says which (DESIGN §7). This only reports. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const when = (iso: string) => `${iso.slice(11, 16)} ${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

function Row({ i }: { i: Incident }) {
  const critical = i.severity === "critical";
  return (
    <li className="border-t border-zinc-800/70 py-1.5">
      <p className={critical ? "text-rose-300" : "text-amber-200"}>
        <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.08em]">{critical ? "critical" : i.severity}</span>
        {i.summary}
      </p>
      <p className="text-zinc-500">
        {i.area} · opened {when(i.opened_at)} · seen {i.seen_count} time{i.seen_count === 1 ? "" : "s"}
        {i.resolved_at ? ` · resolved ${when(i.resolved_at)}` : ""}
      </p>
      {i.repairs.length > 0 && (
        <ul className="mt-0.5 space-y-0.5 text-zinc-400">
          {i.repairs.slice(-3).map((r, k) => <li key={k}>{when(r.at)} · {r.detail}</li>)}
        </ul>
      )}
    </li>
  );
}

export function SystemHealth({ data }: { data: Sentinel | null }) {
  const [open, setOpen] = useState(false);
  if (!data || !data.checked_at) {
    return <p className="mb-4 text-[11px] text-zinc-600">System health: no check yet — the watchdog runs one every ten minutes.</p>;
  }
  const checked = data.checked_at.slice(11, 16);
  const phone = data.ntfy ? "alerts to your phone on" : "alerts to this Mac only";
  if (!data.open.length) {
    return (
      <div className="mb-4 text-[11px] text-zinc-600">
        All system checks passing · {checked} IST · {phone}
        {data.recent.length > 0 && (
          <button id="health-recent" type="button" onClick={() => setOpen(!open)} aria-expanded={open}
            className="ml-1 underline decoration-zinc-700 underline-offset-2 hover:text-zinc-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
            · {data.recent.length} in the last two weeks
          </button>
        )}
        {open && <ul className="mt-1 text-[11px]">{data.recent.map((i) => <Row key={i.id} i={i} />)}</ul>}
      </div>
    );
  }
  const critical = data.open.some((i) => i.severity === "critical");
  const oldest = data.open[0];
  return (
    <div className={`mb-4 rounded-lg border px-3 py-2 text-[12px] ${critical
      ? "border-rose-500/30 bg-rose-500/[0.05] text-rose-200" : "border-amber-500/30 bg-amber-500/[0.05] text-amber-200"}`}>
      <button id="health-open" type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="w-full min-h-8 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
        System health: {data.open.length} open{critical ? " (critical)" : ""} · {oldest.summary.slice(0, 90)}
        {oldest.summary.length > 90 ? "…" : ""} · since {when(oldest.opened_at)}
        <span className="opacity-70"> · checked {checked} IST · {phone} {open ? "▴" : "▾"}</span>
      </button>
      {open && <ul className="mt-1 text-[11px]">{data.open.map((i) => <Row key={i.id} i={i} />)}</ul>}
    </div>
  );
}
