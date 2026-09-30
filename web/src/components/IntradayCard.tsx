"use client";

import { useEffect, useState } from "react";
import type { Intraday, IntradayRule, LiveTick } from "@/lib/api";
import { subscribeToTick } from "@/lib/api";
import { Offline, Panel, Pill, fmtPct, minus } from "./ui";

const STATUS: Record<IntradayRule["status"], { label: string; tone: "neutral" | "info" | "warn" }> = {
  waiting: { label: "waiting", tone: "neutral" },
  in_trade: { label: "triggered", tone: "info" },
  closed: { label: "done for the day", tone: "neutral" },
  no_trade: { label: "no trigger", tone: "neutral" },
  no_history: { label: "no data", tone: "warn" },
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function day(iso: string) {
  return `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
}

function num(v: number | null | undefined) {
  return v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/** What the rule is watching, or did, in index levels the API computed. */
function Levels({ r }: { r: IntradayRule }) {
  const side = r.side === 1 ? "call" : r.side === -1 ? "put" : null;
  if (r.name === "noise_band") {
    if (r.status === "waiting" && r.next?.upper != null)
      return <>At the {r.next.at} close: above <b>{num(r.next.upper)}</b> triggers the call side, below <b>{num(r.next.lower)}</b> the put side.</>;
    if (r.status === "in_trade" && r.next)
      return <>The rule holds while the {r.next.at} close stays {r.side === 1 ? <>above <b>{num(r.next.upper)}</b></> : <>below <b>{num(r.next.lower)}</b></>}; flat at 15:25.</>;
  }
  if (r.name === "last_half_hour" && r.first_half_hour_pts != null && side)
    return <>09:45 against the previous close ({num(r.previous_close)}): <b>{r.first_half_hour_pts > 0 ? "+" : "−"}{num(Math.abs(r.first_half_hour_pts))}</b> pts, so the rule&apos;s side is the {side}, held 15:00 to 15:25.</>;
  if (r.name === "opening_range_5m" && r.first_candle && side)
    return <>First candle {num(r.first_candle.open)} → {num(r.first_candle.close)}: the rule&apos;s side is the {side} from 09:20, stop at <b>{num(r.stop)}</b>, flat at 15:25.</>;
  if (r.entry_index != null)
    return <>In at {num(r.entry_index)} ({r.entry_time}){r.exit_index != null && <>, out at {num(r.exit_index)} ({r.exit_time})</>}.</>;
  return null;
}

/** The pipeline's three intraday rules, followed on today's completed 5-minute bars. */
export function IntradayCard({ initial }: { initial: Intraday | null }) {
  // The rules' state is refreshed with the page (every minute in a session);
  // the price of any contract a rule bought rides on the shared tick.
  const [marks, setMarks] = useState<Record<string, number>>({});
  useEffect(() => subscribeToTick((t: LiveTick) => setMarks(t.intraday?.marks ?? {})), []);

  if (!initial) return <Offline what="The intraday rules" />;
  if (!initial.session) return <Panel className="p-4 text-sm text-zinc-500">No 5-minute bars yet.</Panel>;

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs text-zinc-300">
          Session {day(initial.session)} · bars to {initial.bars_through} IST
        </p>
        <span className="text-[11px] text-zinc-500">5-minute bars: {initial.source}</span>
      </div>
      {initial.missing_after && initial.missing_after.length > 0 && (
        <p className="mt-1 text-[11px] text-amber-300/80">
          The 5-minute bars for {initial.missing_after.map(day).join(", ")} are not available yet, so this is the session before.
        </p>
      )}

      <div className="mt-3 flex flex-col gap-2">
        {initial.rules.map((r) => {
          const st = STATUS[r.status];
          const live = marks[r.name];
          const ev = r.evidence;
          return (
            <div key={r.name} className="rounded-lg bg-zinc-950/60 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  {r.side != null && (
                    <span className={`font-mono text-[10px] font-bold ${r.side === 1 ? "text-emerald-400" : "text-rose-400"}`}>
                      {r.side === 1 ? "CE" : "PE"}
                    </span>
                  )}
                  <span className="text-sm font-medium text-zinc-100">{r.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Pill tone={st.tone}>{st.label}</Pill>
                  {ev && <Pill tone={ev.verdict === "APPROVED" ? "good" : ev.verdict === "CONDITIONAL" ? "warn" : "bad"}>{ev.verdict}</Pill>}
                </div>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-zinc-300">{r.line}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-zinc-500 [&_b]:font-mono [&_b]:font-normal [&_b]:tabular-nums [&_b]:text-zinc-300">
                <Levels r={r} />
              </p>
              {r.contract && (
                <p className="mt-1 font-mono text-[11px] tabular-nums text-zinc-500">
                  NIFTY {day(r.contract.expiry)} {r.contract.strike.toLocaleString("en-IN")} {r.contract.option_type}
                  {live != null && <span className="text-zinc-300"> · now ₹{num(live)}</span>}
                  {r.recorded_today.map((e) => (
                    <span key={e.kind}>
                      {" "}· {e.kind === "entry" ? `recorded in at ask ₹${num(e.ask)}` : `out at bid ₹${num(e.bid)}`}
                      {e.price_at ? ` (${e.price_at.slice(11, 16)})` : ""}
                    </span>
                  ))}
                </p>
              )}
              <p className="mt-1 text-[11px] text-zinc-600">
                {ev && <>2024–26 (modelled): {fmtPct(ev.holdout_mean_pct, 1)} vs {fmtPct(ev.holdout_baseline_pct, 1)} a trade with no signal, t {minus(ev.holdout_t)} (bar {minus(ev.required_t)}). </>}
                {r.forward
                  ? <>At real prices since {day(r.forward.first_day)}: {r.forward.trades} counted of {r.forward.recorded}{r.forward.mean_pct != null && <>, {fmtPct(r.forward.mean_pct, 1)} a trade</>}.</>
                  : <>At real prices: nothing recorded yet.</>}
              </p>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">{initial.note}</p>
    </Panel>
  );
}
