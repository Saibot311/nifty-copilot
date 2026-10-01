"use client";

import { useEffect, useState } from "react";
import type { LiveLeg, MoveCell, MoveLeg, OptionMoves, OptionMovesLive } from "@/lib/api";
import { subscribeToTick } from "@/lib/api";
import { Offline, Panel } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;

/** The leg's figures at a horizon: its own cell, or the instant move. */
function cellOf(leg: MoveLeg | null, horizon: string): MoveCell | null {
  if (!leg) return null;
  return leg.at?.[horizon] ?? (horizon === "now" && leg.up_pct && leg.down_pct
    ? { flat: 0, flat_pct: 0, up: leg.up, down: leg.down, up_pct: leg.up_pct, down_pct: leg.down_pct } : null);
}

function Num({ v, pct }: { v: number | null | undefined; pct?: number | null }) {
  if (v == null) return <span className="text-zinc-600">–</span>;
  return (
    <span className={v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-zinc-400"}>
      {signed(v)}
      {pct != null && <span className="hidden text-zinc-500 sm:inline"> ({signed(pct, 0)}%)</span>}
    </span>
  );
}

function Change({ cell, dir, move }: { cell: MoveCell | null; dir: "up" | "down"; move: number }) {
  return <Num v={cell?.[dir]?.[String(move)]} pct={cell?.[dir === "up" ? "up_pct" : "down_pct"]?.[String(move)]} />;
}

function LiveCell({ leg, align }: { leg: LiveLeg | null; align: "right" | "left" }) {
  if (!leg) return <td className={`py-1.5 px-2 text-${align} text-zinc-600`}>–</td>;
  return (
    <td className={`py-1.5 px-2 text-${align}`}>
      <span className="text-zinc-100">{leg.price.toFixed(1)}</span>{" "}
      <Num v={leg.change} pct={leg.change_pct} />
    </td>
  );
}

/** The contracts repriced at the index now, from the shared tick. */
function LiveTable({ live }: { live: OptionMovesLive }) {
  return (
    <>
      <p className="mt-2 text-[11px] text-zinc-400">
        NIFTY now <span className="font-mono tabular-nums text-zinc-100">{live.index.toLocaleString("en-IN")}</span>,{" "}
        <Num v={live.move} /> since the chain&apos;s {live.prices_as_of} prices. Premiums the model expects at this level, now
        (decay since then included):
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="py-1.5 px-2 text-right font-medium">Call now ≈</th>
              <th className="py-1.5 px-2 text-center font-medium">Strike</th>
              <th className="py-1.5 px-2 text-left font-medium">Put now ≈</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {live.rows.map((r) => (
              <tr key={r.strike} className={`border-t border-zinc-800/70 ${r.is_atm ? "bg-indigo-500/10" : ""}`}>
                <LiveCell leg={r.call} align="right" />
                <td className={`py-1.5 px-2 text-center ${r.is_atm ? "text-zinc-100" : "text-zinc-400"}`}>{r.strike.toLocaleString("en-IN")}</td>
                <LiveCell leg={r.put} align="left" />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-zinc-500">
        An estimate of the premiums from NIFTY&apos;s move as it happens, not a forecast of NIFTY: it follows the index, it
        does not lead it. Volatility is held where the chain had it; the real price will differ when volatility moves.
      </p>
    </>
  );
}

/** What an index move does to the premiums 8 strikes either side of the money. */
export function OptionMovesCard({ data }: { data: OptionMoves | null }) {
  const [move, setMove] = useState(50);
  const [when, setWhen] = useState("now");
  const [mode, setMode] = useState<"moves" | "live">("moves");
  const [live, setLive] = useState<OptionMovesLive | null>(null);
  // Repriced on every tick of the shared poller; no timer of its own.
  useEffect(() => subscribeToTick((t) => setLive(t.option_moves_live ?? null)), []);
  if (!data) return <Offline what="Option price moves" />;
  const showLive = mode === "live" && live != null && live.expiry === data.expiry;
  const m = data.moves.includes(move) ? move : data.moves[0];
  const hz = data.horizons ?? [{ key: "now", label: "Instantly", at: "", hours_from_now: 0 }];
  const h = hz.some((x) => x.key === when) ? when : "now";
  const atm = data.rows.find((r) => r.is_atm);
  const wait = (leg: MoveLeg | null) => cellOf(leg, h)?.flat;
  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-zinc-300">
          NIFTY {data.spot.toLocaleString("en-IN")} · expiry {day(data.expiry)} ({data.days_to_expiry}d) · if the index moves
        </p>
        <div className="flex gap-1" role="group" aria-label="Index move">
          {data.moves.map((x) => (
            <button key={x} type="button" onClick={() => { setMove(x); setMode("moves"); }} aria-pressed={!showLive && x === m}
              className={`rounded-md px-2 py-1 font-mono text-[11px] tabular-nums ${!showLive && x === m ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}>
              ±{x}
            </button>
          ))}
          {live && live.expiry === data.expiry && (
            <button type="button" onClick={() => setMode("live")} aria-pressed={showLive}
              className={`rounded-md px-2 py-1 text-[11px] ${showLive ? "bg-indigo-500/30 text-indigo-100" : "text-indigo-300 hover:text-indigo-200"}`}>
              Live now
            </button>
          )}
        </div>
      </div>

      {showLive ? <LiveTable live={live!} /> : <>
      <div className="mt-2 flex flex-wrap items-center gap-1" role="group" aria-label="By when">
        {hz.map((x) => (
          <button key={x.key} type="button" onClick={() => setWhen(x.key)} aria-pressed={x.key === h}
            className={`rounded-md px-2 py-1 text-[11px] ${x.key === h ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}>
            {x.label}
          </button>
        ))}
      </div>
      {h !== "now" && atm && (
        <p className="mt-2 text-[11px] text-zinc-400">
          If NIFTY does not move: the {atm.strike.toLocaleString("en-IN")} call <Num v={wait(atm.call)} />, the put <Num v={wait(atm.put)} /> by then.
        </p>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="hidden py-1.5 pr-2 text-right font-medium sm:table-cell">Call now</th>
              <th className="hidden py-1.5 pr-2 text-right font-medium md:table-cell">No move</th>
              <th className="py-1.5 pr-2 text-right font-medium">Call +{m}</th>
              <th className="py-1.5 pr-2 text-right font-medium">Call −{m}</th>
              <th className="py-1.5 px-2 text-center font-medium">Strike</th>
              <th className="py-1.5 pl-2 text-left font-medium">Put +{m}</th>
              <th className="py-1.5 pl-2 text-left font-medium">Put −{m}</th>
              <th className="hidden py-1.5 pl-2 text-left font-medium md:table-cell">No move</th>
              <th className="hidden py-1.5 pl-2 text-left font-medium sm:table-cell">Put now</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {data.rows.map((r) => (
              <tr key={r.strike} className={`border-t border-zinc-800/70 ${r.is_atm ? "bg-indigo-500/10" : ""}`}>
                <td className="hidden py-1.5 pr-2 text-right text-zinc-400 sm:table-cell">
                  {r.call ? r.call.price.toFixed(1) : "–"}
                  {r.call_measured != null && <span className="text-zinc-600"> · {r.call_measured.toFixed(2).replace("-", "−")}/pt</span>}
                </td>
                <td className="hidden py-1.5 pr-2 text-right md:table-cell"><Num v={cellOf(r.call, h)?.flat} /></td>
                <td className="py-1.5 pr-2 text-right"><Change cell={cellOf(r.call, h)} dir="up" move={m} /></td>
                <td className="py-1.5 pr-2 text-right"><Change cell={cellOf(r.call, h)} dir="down" move={m} /></td>
                <td className={`py-1.5 px-2 text-center ${r.is_atm ? "text-zinc-100" : "text-zinc-400"}`}>{r.strike.toLocaleString("en-IN")}</td>
                <td className="py-1.5 pl-2"><Change cell={cellOf(r.put, h)} dir="up" move={m} /></td>
                <td className="py-1.5 pl-2"><Change cell={cellOf(r.put, h)} dir="down" move={m} /></td>
                <td className="hidden py-1.5 pl-2 md:table-cell"><Num v={cellOf(r.put, h)?.flat} /></td>
                <td className="hidden py-1.5 pl-2 text-zinc-400 sm:table-cell">
                  {r.put ? r.put.price.toFixed(1) : "–"}
                  {r.put_measured != null && <span className="text-zinc-600"> · {r.put_measured.toFixed(2).replace("-", "−")}/pt</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </>}
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        Change in premium, ₹ per unit (a lot is 65 units), and as % of the premium. {data.note}
        {data.measured_session ? ` "/pt" is measured on ${day(data.measured_session)} (${data.measured_snapshots} snapshots).` : " No snapshots recorded for this expiry yet."}{" "}
        Prices from NSE&apos;s chain as of {data.as_of}{data.forward ? `; valued against the forward ${data.forward.toLocaleString("en-IN")} (${data.forward_basis})` : ""}.
      </p>
    </Panel>
  );
}
