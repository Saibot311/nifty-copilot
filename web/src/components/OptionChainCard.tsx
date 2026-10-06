"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChainContract, OptionChainTable } from "@/lib/api";
import { fetchOptionChainTable } from "@/lib/api";
import { Offline, Panel, Pill, Stat, fmtNum, fmtPct, fmtSigned } from "./ui";

/** The option chain: every strike NSE lists for any expiry it lists, each
 *  call and put with its prices, and — for the one you pick — what a lot costs
 *  to buy now and where it breaks even. It replaced the separate open-interest
 *  card (2026-09-29): that card's summary is the stat row at the top, for
 *  whichever expiry is picked, and its bars sit behind the OI figures, growing
 *  outward from the strike column with the two heaviest strikes brightest.
 *
 *  Calls sit left and puts right, as on NSE and Kite. In-the-money cells are
 *  shaded in zinc, not coloured: DESIGN.md §2 keeps emerald and rose for money
 *  made and lost, and a call is neither. Indigo marks the contract you picked,
 *  because picking is interaction. Every figure is the API's (§1); the only
 *  thing done here is formatting.
 */

type Kind = "CE" | "PE";

const price = (v: number | null) => (v == null ? "–" : v.toFixed(2));
const rupees = (v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const compact = (v: number) => {
  const lakh = v / 100_000;
  if (Math.abs(lakh) >= 1) return `${lakh.toFixed(1)}L`;
  const k = v / 1000;
  return Math.abs(k) >= 1 ? `${k.toFixed(0)}k` : `${Math.round(v)}`;
};
const compactSigned = (v: number) => (v === 0 ? "0" : `${v > 0 ? "+" : "−"}${compact(Math.abs(v))}`);
const sideName = (k: Kind) => (k === "CE" ? "call" : "put");

/** One side of a strike's row, in the column order NSE uses: open interest
 *  on the outside, the price next to the strike. `mirror` flips it for puts. */
function Side({ c, kind, strike, selected, onPick, mirror, maxOi, peak }: {
  c: ChainContract | null; kind: Kind; strike: number; selected: boolean; onPick: () => void; mirror: boolean;
  maxOi: number; peak: boolean;
}) {
  const shade = selected ? "bg-indigo-500/10" : c?.itm ? "bg-zinc-800/40" : "";
  const td = `px-2 py-1.5 text-right ${shade}`;
  if (!c) {
    // NSE lists no contract on this side of the strike.
    const blank = [
      <td key="oi" className={td} />, <td key="oic" className={`${td} hidden lg:table-cell`} />,
      <td key="vol" className={`${td} hidden lg:table-cell`} />, <td key="iv" className={`${td} hidden sm:table-cell`} />,
      <td key="ltp" className={td} />, <td key="chg" className={`${td} hidden lg:table-cell`} />,
      <td key="ba" className={`${td} hidden xl:table-cell`} />,
    ];
    return <>{mirror ? blank.reverse() : blank}</>;
  }
  const click = { onClick: onPick };
  const cells = [
    <td key="oi" {...click} className={`${td} relative cursor-pointer text-zinc-400`}
        title={`${c.oi.toLocaleString("en-IN")} ${sideName(kind)} OI at ${strike.toLocaleString("en-IN")}`}>
      {/* The open-interest bar: one scale for both sides, growing away from the strike. */}
      <span aria-hidden className={`absolute inset-y-1 ${mirror ? "left-0" : "right-0"} rounded-[2px] ${
        peak ? "bg-zinc-300/35" : "bg-zinc-500/20"}`} style={{ width: `${(c.oi / maxOi) * 100}%` }} />
      <span className="relative">{compact(c.oi)}</span>
    </td>,
    <td key="oic" {...click} className={`${td} hidden cursor-pointer text-zinc-500 lg:table-cell`}>{compactSigned(c.oi_change)}</td>,
    <td key="vol" {...click} className={`${td} hidden cursor-pointer text-zinc-500 lg:table-cell`}>{compact(c.volume)}</td>,
    <td key="iv" {...click} className={`${td} hidden cursor-pointer text-zinc-500 sm:table-cell`}>{c.iv == null ? "–" : c.iv.toFixed(1)}</td>,
    <td key="ltp" className={`${shade} p-0`}>
      <button
        type="button" onClick={onPick} aria-pressed={selected}
        aria-label={`Buyer's view of the ${strike.toLocaleString("en-IN")} ${sideName(kind)}`}
        className={`min-h-8 w-full px-2 py-1.5 text-right font-medium text-zinc-100 hover:bg-zinc-800/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500/60 ${
          mirror ? "text-left" : ""}`}
      >
        {price(c.ltp)}
        {/* Below lg the Chg column is hidden, so the day's change rides under
            the price: a phone should not show a chain with no change on it. */}
        <span className="block text-[10px] font-normal text-zinc-500 lg:hidden">{fmtSigned(c.change)}</span>
      </button>
    </td>,
    <td key="chg" {...click} className={`${td} hidden cursor-pointer text-zinc-500 lg:table-cell`}>{fmtSigned(c.change)}</td>,
    <td key="ba" {...click} className={`${td} hidden cursor-pointer whitespace-nowrap text-zinc-500 xl:table-cell`}>
      {price(c.bid)} / {price(c.ask)}
    </td>,
  ];
  return <>{mirror ? cells.reverse() : cells}</>;
}

/** What one lot of the picked contract costs to buy now. */
function BuyerView({ data, pick }: { data: OptionChainTable; pick: { strike: number; kind: Kind } | null }) {
  if (!pick) {
    return (
      <p className="text-[13px] text-zinc-400">
        Pick any call or put price in the table to see what one lot costs to buy now, what it pays in charges,
        and where it breaks even at expiry.
      </p>
    );
  }
  const row = data.rows.find((r) => r.strike === pick.strike);
  const c = row ? (pick.kind === "CE" ? row.call : row.put) : null;
  const name = `${pick.strike.toLocaleString("en-IN")} ${sideName(pick.kind)}`;
  if (!c) return <p className="text-[13px] text-zinc-400">The {data.expiry} expiry has no {name}.</p>;
  const b = c.buyer;
  const where = Math.abs(c.moneyness_pct) < 0.005 ? "at the money"
    : `${Math.abs(c.moneyness_pct).toFixed(2)}% ${c.itm ? "in" : "out of"} the money`;

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm font-semibold text-zinc-100">{name}</span>
        <span className="text-[12px] text-zinc-400">
          {data.expiry} · {data.days_to_expiry} day{data.days_to_expiry === 1 ? "" : "s"} to expiry
        </span>
        <Pill>{where}</Pill>
        <span className="font-mono text-[10px] text-zinc-600">{c.identifier}</span>
      </div>
      {!b ? (
        <p className="mt-2 text-[13px] text-zinc-400">NSE shows no price for the {name}: no trade and no ask, so nothing to buy at.</p>
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="One lot" value={rupees(b.lot_rs)}
                sub={`${data.lot_size} × ${price(b.price)} ${b.price_source === "ask" ? "ask" : "last trade — no ask"}`} />
          <Stat label="Charges, in and out" value={rupees(b.charges_rs)}
                sub={`${rupees(b.buy_charges_rs)} to buy, ${rupees(b.sell_charges_rs)} to sell`} />
          <Stat label="Spread, one lot" value={b.spread_rs == null ? "–" : rupees(b.spread_rs)}
                sub={b.spread_rs == null ? "no bid and ask on the book" : `bid ${price(c.bid)} · ask ${price(c.ask)}`} />
          <Stat label="Breaks even at expiry" value={fmtNum(b.breakeven)}
                sub={`NIFTY ${b.needs_move_pts >= 0 ? "up" : "down"} ${Math.abs(b.needs_move_pts).toLocaleString("en-IN")} pts (${fmtPct(b.needs_move_pct)})`} />
        </div>
      )}
      {b && (
        <a id="chain-precheck" href={`?tab=journal&check=${pick.kind}:${pick.strike}:${data.expiry}`}
          className="mt-3 inline-flex min-h-8 items-center rounded-md border border-zinc-700 px-3 text-[12px] text-zinc-200 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
          Check it before buying: the move you need by when you plan to sell →
        </a>
      )}
    </div>
  );
}

export function OptionChainCard({ initial }: { initial?: OptionChainTable | null }) {
  const [expiry, setExpiry] = useState<string | null>(initial?.expiry ?? null);
  const [other, setOther] = useState<OptionChainTable | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "failed">(initial ? "idle" : "loading");
  const [pick, setPick] = useState<{ strike: number; kind: Kind } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const atm = useRef<HTMLTableRowElement>(null);
  const centredFor = useRef<string | null>(null);

  // The nearest expiry comes with the page and is kept current by its
  // AutoRefresh. Any other expiry is asked for when picked, and again each
  // time the page refreshes — so it rides the same clock, with no timer here.
  const wantsOther = !initial || expiry !== initial.expiry;
  useEffect(() => {
    if (!wantsOther) return;
    let alive = true;
    fetchOptionChainTable(expiry ?? undefined).then((r) => {
      if (!alive) return;
      if (r.data) { setOther(r.data); setState("idle"); if (!expiry) setExpiry(r.data.expiry); }
      else setState("failed");
    });
    return () => { alive = false; };
  }, [wantsOther, expiry, initial]);

  const data = !wantsOther ? initial! : other && other.expiry === expiry ? other : null;

  const centre = useCallback(() => {
    const b = box.current, r = atm.current;
    if (b && r) b.scrollTop = r.offsetTop - b.clientHeight / 2 + r.clientHeight / 2;
  }, []);
  // Open each expiry at the money — once, so a refresh never yanks the table
  // away from where you scrolled to.
  useEffect(() => {
    if (data && centredFor.current !== data.expiry) { centredFor.current = data.expiry; centre(); }
  }, [data, centre]);

  if (!initial && !other && state !== "loading") {
    return <Offline what="The option chain" why="NSE's option chain did not answer." />;
  }
  const expiries = (data ?? initial ?? other)?.expiries ?? [];
  const spotAt = data ? data.rows.findIndex((r) => r.strike > data.underlying_value) : -1;
  // Bar length only: a scale for drawing, not a figure anyone reads.
  const maxOi = data ? Math.max(...data.rows.flatMap((r) => [r.call?.oi ?? 0, r.put?.oi ?? 0]), 1) : 1;
  const oi = data?.open_interest;

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="chain-expiry" className="text-[12px] text-zinc-400">Expiry</label>
          <select
            id="chain-expiry" value={expiry ?? ""}
            onChange={(e) => { setExpiry(e.target.value); if (e.target.value !== initial?.expiry) setState("loading"); }}
            className="min-h-8 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-[13px] tabular-nums text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60"
          >
            {expiries.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
          <button
            type="button" onClick={centre} disabled={!data}
            className="min-h-8 rounded-lg border border-zinc-700 px-2.5 py-1 text-[12px] text-zinc-300 hover:bg-zinc-800 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60"
          >
            Back to the money
          </button>
        </div>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {data ? `${data.strikes} strikes · NIFTY ${fmtNum(data.underlying_value)} · NSE ${data.as_of || "—"}` : ""}
        </span>
      </div>

      {oi && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Put/call OI" value={oi.pcr ?? "–"}
                sub={`${compact(oi.total_put)} puts / ${compact(oi.total_call)} calls`} />
          <Stat label="Most puts" value={oi.max_put_oi_strike?.toLocaleString("en-IN") ?? "–"}
                sub="read as support — untested here" />
          <Stat label="Most calls" value={oi.max_call_oi_strike?.toLocaleString("en-IN") ?? "–"}
                sub="read as resistance — untested here" />
          <Stat label="Opened today" value={`${compactSigned(oi.put_oi_added)} puts`}
                sub={`${compactSigned(oi.call_oi_added)} calls`} />
        </div>
      )}

      {data && (
        <div className="mt-4 border-t border-zinc-800 pt-3">
          <BuyerView data={data} pick={pick} />
        </div>
      )}

      <div className="mt-4">
        {!data ? (
          <p className="py-8 text-center text-[13px] text-zinc-500">
            {state === "failed" ? `NSE's chain for ${expiry} did not answer. It is asked again on the next refresh.`
              : `Loading the ${expiry ?? "nearest"} chain…`}
          </p>
        ) : (
          <>
          <div className="mb-1 flex justify-between px-2 text-[10px] uppercase tracking-[0.1em] text-zinc-500">
            <span>Calls</span><span>Puts</span>
          </div>
          <div ref={box} className="relative max-h-[30rem] overflow-auto rounded-lg border border-zinc-800/60">
            <table className="w-full border-collapse font-mono text-[11px] tabular-nums">
              <thead className="sticky top-0 z-10 bg-zinc-950 text-[10px] uppercase tracking-[0.08em] text-zinc-500">
                <tr className="border-b border-zinc-800">
                  <th className="px-2 py-1 text-right font-medium">OI</th>
                  <th className="hidden px-2 py-1 text-right font-medium lg:table-cell">Chg OI</th>
                  <th className="hidden px-2 py-1 text-right font-medium lg:table-cell">Volume</th>
                  <th className="hidden px-2 py-1 text-right font-medium sm:table-cell">IV</th>
                  <th className="px-2 py-1 text-right font-medium">Price</th>
                  <th className="hidden px-2 py-1 text-right font-medium lg:table-cell">Chg</th>
                  <th className="hidden px-2 py-1 text-right font-medium xl:table-cell">Bid / Ask</th>
                  <th className="px-2 py-1 text-center font-medium text-zinc-400">Strike</th>
                  <th className="hidden px-2 py-1 text-right font-medium xl:table-cell">Bid / Ask</th>
                  <th className="hidden px-2 py-1 text-right font-medium lg:table-cell">Chg</th>
                  <th className="px-2 py-1 text-left font-medium">Price</th>
                  <th className="hidden px-2 py-1 text-right font-medium sm:table-cell">IV</th>
                  <th className="hidden px-2 py-1 text-right font-medium lg:table-cell">Volume</th>
                  <th className="hidden px-2 py-1 text-right font-medium lg:table-cell">Chg OI</th>
                  <th className="px-2 py-1 text-right font-medium">OI</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                    // The first strike above spot carries a bright rule: NIFTY sits on that line.
                    <tr key={r.strike} ref={r.is_atm ? atm : undefined}
                        className={`border-b border-zinc-900 ${i === spotAt ? "border-t-2 border-t-zinc-400" : ""}`}>
                      <Side c={r.call} kind="CE" strike={r.strike} mirror={false} maxOi={maxOi}
                            peak={r.strike === oi?.max_call_oi_strike}
                            selected={pick?.strike === r.strike && pick.kind === "CE"}
                            onPick={() => setPick({ strike: r.strike, kind: "CE" })} />
                      <td className={`bg-zinc-900/60 px-2 py-1.5 text-center ${r.is_atm ? "font-semibold text-zinc-100" : "text-zinc-300"}`}>
                        {r.strike.toLocaleString("en-IN")}
                      </td>
                      <Side c={r.put} kind="PE" strike={r.strike} mirror maxOi={maxOi}
                            peak={r.strike === oi?.max_put_oi_strike}
                            selected={pick?.strike === r.strike && pick.kind === "PE"}
                            onPick={() => setPick({ strike: r.strike, kind: "PE" })} />
                    </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>

      {data && (
        <p className="mt-3 border-t border-zinc-800 pt-2 text-[11px] leading-relaxed text-zinc-500">
          Prices are NSE&apos;s at {data.as_of || "the last update"}; shaded cells are in the money, and the bright rule is where NIFTY sits. A lot is{" "}
          {data.lot_size} bought at the ask. Charges are {data.rate_card}, on the way in and on a sale at the same
          price; the spread is the real one on the book rather than the backtests&apos; assumed 1.5%. The breakeven
          counts the premium and both legs&apos; charges. This is what a contract costs, not whether it is worth
          buying. The bar behind each OI figure is open interest on one scale for both sides; the brightest two
          are the heaviest strikes named above. Those are commonly read as support (puts) and resistance (calls),
          and the put/call ratio as sentiment, but this project has not tested whether either predicts anything on
          NIFTY: they are measurements, not signals.
        </p>
      )}
    </Panel>
  );
}
