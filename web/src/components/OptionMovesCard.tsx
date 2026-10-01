"use client";

import { useState } from "react";
import type { MoveLeg, OptionMoves } from "@/lib/api";
import { Offline, Panel } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;

function Change({ leg, dir, move }: { leg: MoveLeg | null; dir: "up" | "down"; move: number }) {
  const v = leg?.[dir]?.[String(move)];
  if (v == null) return <span className="text-zinc-600">–</span>;
  const pct = leg?.[dir === "up" ? "up_pct" : "down_pct"]?.[String(move)];
  return (
    <span className={v > 0 ? "text-emerald-400" : "text-rose-400"}>
      {signed(v)}
      {pct != null && <span className="hidden text-zinc-500 sm:inline"> ({signed(pct, 0)}%)</span>}
    </span>
  );
}

/** What an index move does to the premiums 8 strikes either side of the money. */
export function OptionMovesCard({ data }: { data: OptionMoves | null }) {
  const [move, setMove] = useState(50);
  if (!data) return <Offline what="Option price moves" />;
  const m = data.moves.includes(move) ? move : data.moves[0];
  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-zinc-300">
          NIFTY {data.spot.toLocaleString("en-IN")} · expiry {day(data.expiry)} ({data.days_to_expiry}d) · if the index moves
        </p>
        <div className="flex gap-1" role="group" aria-label="Index move">
          {data.moves.map((x) => (
            <button key={x} type="button" onClick={() => setMove(x)} aria-pressed={x === m}
              className={`rounded-md px-2 py-1 font-mono text-[11px] tabular-nums ${x === m ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}>
              ±{x}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="hidden py-1.5 pr-2 text-right font-medium sm:table-cell">Call now</th>
              <th className="py-1.5 pr-2 text-right font-medium">Call +{m}</th>
              <th className="py-1.5 pr-2 text-right font-medium">Call −{m}</th>
              <th className="py-1.5 px-2 text-center font-medium">Strike</th>
              <th className="py-1.5 pl-2 text-left font-medium">Put +{m}</th>
              <th className="py-1.5 pl-2 text-left font-medium">Put −{m}</th>
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
                <td className="py-1.5 pr-2 text-right"><Change leg={r.call} dir="up" move={m} /></td>
                <td className="py-1.5 pr-2 text-right"><Change leg={r.call} dir="down" move={m} /></td>
                <td className={`py-1.5 px-2 text-center ${r.is_atm ? "text-zinc-100" : "text-zinc-400"}`}>{r.strike.toLocaleString("en-IN")}</td>
                <td className="py-1.5 pl-2"><Change leg={r.put} dir="up" move={m} /></td>
                <td className="py-1.5 pl-2"><Change leg={r.put} dir="down" move={m} /></td>
                <td className="hidden py-1.5 pl-2 text-zinc-400 sm:table-cell">
                  {r.put ? r.put.price.toFixed(1) : "–"}
                  {r.put_measured != null && <span className="text-zinc-600"> · {r.put_measured.toFixed(2).replace("-", "−")}/pt</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        Change in premium, ₹ per unit (a lot is 65 units), and as % of the premium. {data.note}
        {data.measured_session ? ` "/pt" is measured on ${day(data.measured_session)} (${data.measured_snapshots} snapshots).` : " No snapshots recorded for this expiry yet."}{" "}
        Prices from NSE&apos;s chain as of {data.as_of}.
      </p>
    </Panel>
  );
}
