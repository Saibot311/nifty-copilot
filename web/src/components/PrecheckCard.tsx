"use client";

import { useEffect, useState } from "react";
import { fetchOptionChainTable, fetchPrecheck, type OptionChainTable, type Precheck, type PrecheckWindow } from "@/lib/api";
import { Panel } from "./ui";

/** Before you buy: the contract you are about to buy, measured against what
 *  the project already knows — the rate card, the live spread, the decay to
 *  when you plan to sell, the NIFTY move that gets your money back, and how
 *  often NIFTY has moved that far that way over the same time since 2015.
 *  Every figure and sentence is the API's (briefing/precheck.py); it marks
 *  what crosses a stated threshold and never says whether to buy.
 *
 *  The option chain's buyer view links here with ?check=CE:22800:13-Oct-2026,
 *  which fills the form. */

const WINDOWS: { id: PrecheckWindow; label: string }[] = [
  { id: "15m", label: "in 15 minutes" }, { id: "30m", label: "in 30 minutes" }, { id: "60m", label: "in an hour" },
  { id: "close", label: "by the session's close" }, { id: "1s", label: "by the next session's close" },
  { id: "2s", label: "within 2 sessions" }, { id: "3s", label: "within 3 sessions" }, { id: "5s", label: "within 5 sessions" },
  { id: "expiry", label: "at expiry" },
];

const rs = (v: number | null | undefined) =>
  v == null ? "–" : `${v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const inputCls = "min-h-9 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60";

export type Prefill = { option_type: "CE" | "PE"; strike: number; expiry: string; quantity: number; entry_premium: number };

function Fact({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className="font-mono text-[15px] tabular-nums text-zinc-100">{value}</div>
      <div className="text-[11px] leading-snug text-zinc-500">{sub}</div>
    </div>
  );
}

export function PrecheckCard({ onLog }: { onLog: (p: Prefill) => void }) {
  const [chain, setChain] = useState<OptionChainTable | null>(null);
  const [expiry, setExpiry] = useState<string>("");
  const [kind, setKind] = useState<"CE" | "PE">("CE");
  const [strike, setStrike] = useState<string>("");
  const [lots, setLots] = useState("1");
  const [premium, setPremium] = useState("");
  const [window_, setWindow] = useState<PrecheckWindow>("close");
  const [result, setResult] = useState<Precheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // A link from the option chain fills the form (read after hydration, as the tabs do).
  useEffect(() => {
    const id = window.setTimeout(() => {
      const c = new URLSearchParams(window.location.search).get("check");
      const [k, s, e] = (c ?? "").split(":");
      if ((k === "CE" || k === "PE") && Number(s) > 0 && /^\d{2}-[A-Za-z]{3}-\d{4}$/.test(e ?? "")) {
        setKind(k); setStrike(s); setExpiry(e);
      }
    }, 0);
    return () => window.clearTimeout(id);
  }, []);

  // The chain for the picked expiry gives the strikes to choose from (the nearest when none is picked).
  useEffect(() => {
    let alive = true;
    fetchOptionChainTable(expiry || undefined).then((r) => {
      if (!alive || !r.data) return;
      setChain(r.data);
      if (!expiry) setExpiry(r.data.expiry);
      setStrike((s) => s || String(r.data!.atm_strike));
    });
    return () => { alive = false; };
  }, [expiry]);

  async function check(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const q = new URLSearchParams({ option_type: kind, strike, expiry, lots, window: window_ });
    if (premium) q.set("premium", premium);
    const r = await fetchPrecheck(q);
    setBusy(false);
    if (r.data) setResult(r.data);
    else { setResult(null); setError(r.error ?? "The check did not answer."); }
  }

  const strikes = chain && chain.expiry === expiry ? chain.rows.map((r) => r.strike) : [];
  const c = result?.contract;

  return (
    <Panel className="p-4">
      <form onSubmit={check} className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <fieldset className="col-span-2 flex flex-col gap-1 text-xs text-zinc-400 sm:col-span-1">
          <legend className="mb-1">Option</legend>
          <div className="flex gap-1">
            {(["CE", "PE"] as const).map((k) => (
              <button key={k} id={`pc-${k}`} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}
                className={`min-h-9 flex-1 rounded-md border px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 ${
                  kind === k ? "border-indigo-500/50 bg-indigo-500/15 text-indigo-200" : "border-zinc-700 text-zinc-400"}`}>
                {k === "CE" ? "Call" : "Put"}
              </button>
            ))}
          </div>
        </fieldset>
        <label className="flex flex-col gap-1 text-xs text-zinc-400">Expiry
          <select id="pc-expiry" value={expiry} onChange={(e) => setExpiry(e.target.value)} className={inputCls}>
            {(chain?.expiries ?? (expiry ? [expiry] : [])).map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-400">Strike
          <input id="pc-strike" type="number" step="50" min="0" required list="pc-strikes" value={strike}
            onChange={(e) => setStrike(e.target.value)} className={inputCls} />
          <datalist id="pc-strikes">{strikes.map((s) => <option key={s} value={s} />)}</datalist>
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-400">Lots
          <input id="pc-lots" type="number" min="1" max="100" step="1" required value={lots}
            onChange={(e) => setLots(e.target.value)} className={inputCls} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-400">Price a unit (₹)
          <input id="pc-premium" type="number" min="0" step="any" value={premium} placeholder="the ask"
            onChange={(e) => setPremium(e.target.value)} className={inputCls} />
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-xs text-zinc-400 sm:col-span-1 lg:col-span-1">I plan to sell
          <select id="pc-window" value={window_} onChange={(e) => setWindow(e.target.value as PrecheckWindow)} className={inputCls}>
            {WINDOWS.map((w) => <option key={w.id} value={w.id}>{w.label}</option>)}
          </select>
        </label>
        <div className="col-span-2 flex items-end sm:col-span-1">
          <button id="pc-check" type="submit" disabled={busy || !expiry || !strike}
            className="min-h-9 w-full rounded-md bg-indigo-500/90 px-3.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">
            {busy ? "Checking…" : "Check it"}
          </button>
        </div>
      </form>

      {error && <p role="alert" className="mt-3 text-[13px] text-rose-300">{error}</p>}

      {result && c && (
        <div className="mt-4 space-y-3 border-t border-zinc-800 pt-3" aria-live="polite">
          <p className="text-[13px] text-zinc-200">
            {c.strike.toLocaleString("en-IN")} {c.kind === "CE" ? "call" : "put"}, expiring {c.expiry.slice(8)}/{c.expiry.slice(5, 7)}
            <span className="text-zinc-400"> · {c.lots} lot{c.lots === 1 ? "" : "s"} = {c.quantity} units at ₹{c.premium.toLocaleString("en-IN")} ({result.price_source})
            · sold by {c.exit_at.slice(11, 16)} on {c.exit_at.slice(8, 10)}/{c.exit_at.slice(5, 7)} · NIFTY {result.spot.toLocaleString("en-IN")} ·{" "}
            {result.marked === 0 ? "nothing marked" : `${result.marked} of ${result.checks.length} checks marked`}</span>
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Fact label="NIFTY move to get your money back" value={c.breakeven_pts == null ? "out of reach" : `${c.breakeven_pts.toLocaleString("en-IN", { maximumFractionDigits: 0 })} pts ${c.direction}`}
              sub={`by ${c.exit_at.slice(11, 16)} on ${c.exit_at.slice(8, 10)}/${c.exit_at.slice(5, 7)}`} />
            <Fact label="If NIFTY doesn't move" value={rs(c.flat_rs)} sub={`${c.flat_pct > 0 ? "+" : c.flat_pct < 0 ? "−" : ""}${Math.abs(c.flat_pct)}% of ${rs(c.paid_rs)} paid`} />
            <Fact label="Charges, in and out" value={rs(c.charges_rs)} sub={`${c.charges_pct}% of the premium`} />
            <Fact label="Sold straight away" value={rs(c.sell_now_rs)} sub={c.spread_pct == null ? "no bid on the book" : `spread ${c.spread_pct}% of the price`} />
          </div>
          <ul className="space-y-1.5">
            {result.checks.map((f) => (
              <li key={f.key} className={`border-l-2 pl-2.5 text-[12.5px] leading-relaxed ${
                f.tone === "warn" ? "border-amber-500/70 text-zinc-200" : "border-zinc-700 text-zinc-400"}`}>
                {f.tone === "warn" && <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-300">marked</span>}
                {f.text}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button id="pc-log" type="button"
              onClick={() => onLog({ option_type: c.kind, strike: c.strike, expiry: c.expiry, quantity: c.quantity, entry_premium: c.premium })}
              className="min-h-8 rounded-md border border-zinc-700 px-3 text-[12px] text-zinc-200 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
              Fill the journal with this
            </button>
            <span className="text-[11px] text-zinc-500">Fills the form below; nothing is saved until you add it.</span>
          </div>
          <p className="text-[11px] leading-relaxed text-zinc-500">
            {result.note} Chain {result.chain_as_of}; value modelled from the {result.forward_basis}
            {c.iv != null ? ` at ${c.iv}% implied volatility` : ""}.
          </p>
        </div>
      )}
    </Panel>
  );
}
