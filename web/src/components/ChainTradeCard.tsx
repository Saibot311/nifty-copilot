"use client";

import { useEffect, useState } from "react";
import type { ChainTrade, ChainTradeRules } from "@/lib/api";
import { fetchChainTrade } from "@/lib/api";
import { useStored } from "@/lib/stored";
import { Offline, Panel, Pill, Stat, fmtNum, minus } from "./ui";

/** The Today tab's option-chain trade: one option to buy, with an entry, a
 *  target and a stop-loss, read off the live chain's open-interest build-up,
 *  PCR and IV (api/options/chain_trade.py). The owner's scoped exception to
 *  "never advise a trade" (2026-10-12): it says it is model-generated and
 *  untested, and its default-rules trades are logged to build a record.
 *
 *  The side is emerald for a call and rose for a put, as everywhere a side is
 *  named; amber frames the card because it is "read this before acting". The
 *  rules are per viewer (localStorage); changed rules are asked for once, on
 *  change and on each page refresh, never on a timer of their own. */

const RULES_KEY = "chain_trade_rules";
const STALE_MIN = 10;

const FIELDS: { key: keyof ChainTradeRules; label: string; step: number; hint: string }[] = [
  { key: "near_strikes", label: "Strikes each side", step: 1, hint: "how far from the money the build-up is read" },
  { key: "min_skew_pct", label: "Min skew %", step: 0.5, hint: "puts vs calls added, as a share of OI held there" },
  { key: "pcr_ce_min", label: "PCR at least (call)", step: 0.05, hint: "a call needs PCR this high or more" },
  { key: "pcr_pe_max", label: "PCR at most (put)", step: 0.05, hint: "a put needs PCR this low or less" },
  { key: "iv_max", label: "IV at most %", step: 1, hint: "past this the premium is dear for a buyer" },
  { key: "strike_offset", label: "Strikes out of the money", step: 1, hint: "0 is at the money" },
  { key: "target_pct", label: "Target % of premium", step: 5, hint: "exit target above the entry" },
  { key: "stop_pct", label: "Stop % of premium", step: 5, hint: "stop-loss below the entry" },
];

const rs = (v: number | null) =>
  v == null ? "–" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const premium = (v: number | null) => (v == null ? "–" : v.toFixed(2));

/** NSE's chain timestamp ("12-Oct-2026 12:30:00", IST) in minutes before `now`. */
function ageMinutes(asOf: string | null, now: string): number | null {
  const m = asOf?.match(/^(\d{2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2})/);
  if (!m) return null;
  const mon = "JanFebMarAprMayJunJulAugSepOctNovDec".indexOf(m[2]) / 3 + 1;
  if (mon < 1) return null;
  const t = Date.parse(`${m[3]}-${String(mon).padStart(2, "0")}-${m[1]}T${m[4]}:${m[5]}:00+05:30`);
  return Number.isNaN(t) ? null : Math.round((Date.parse(now) - t) / 60_000);
}

function parseRules(raw: string): Partial<ChainTradeRules> | null {
  if (!raw) return null;
  try { return JSON.parse(raw) as Partial<ChainTradeRules>; } catch { return null; }
}

export function ChainTradeCard({ initial }: { initial: ChainTrade | null }) {
  const [stored, setStored] = useStored(RULES_KEY, "");
  const custom = parseRules(stored);
  // The answer for your own rules, tagged with the request it answers: the
  // rules, and the page render it was asked for with.
  const [mine, setMine] = useState<{ key: string; data: ChainTrade | null } | null>(null);
  const [editing, setEditing] = useState(false);
  const key = `${stored}|${initial?.computed_at ?? ""}`;

  // Rules of your own are asked for when set and again whenever the page
  // refreshes (a new `initial`); the defaults come with the page.
  useEffect(() => {
    const rules = parseRules(stored);
    if (!rules) return;
    let alive = true;
    fetchChainTrade(rules).then((r) => { if (alive) setMine({ key, data: r.data }); });
    return () => { alive = false; };
  }, [stored, key]);

  const answered = mine?.key === key;
  const state = !custom ? "idle" : !answered ? "loading" : mine.data ? "idle" : "failed";
  // While a refresh for your rules is out, the last answer for them stays up.
  const data = custom ? (mine?.key.startsWith(`${stored}|`) ? mine.data : null) : initial;
  if (!initial && !custom) {
    return <Offline what="The option-chain trade" why="NSE's option chain did not answer, so there is nothing to read the trade from." />;
  }
  if (custom && state === "failed") {
    return <Offline what="The option-chain trade" why="The API did not answer for your rules. Reset them, or reload." />;
  }
  if (!data) {
    return (
      <Panel className="p-5">
        <p className="text-sm text-zinc-500" role="status">Reading the chain with your rules…</p>
      </Panel>
    );
  }

  const t = data.trade;
  const age = ageMinutes(data.inputs.as_of, data.computed_at);
  const stale = data.market_open && age != null && age > STALE_MIN;
  const sideTone = t?.side === "CE" ? "text-emerald-400" : "text-rose-400";

  return (
    <Panel className="overflow-hidden border-amber-500/25 bg-amber-500/[0.03]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800/70 px-5 py-4">
        <div className="min-w-0">
          {t ? (
            <p className="text-xl font-semibold tracking-tight">
              <span className={sideTone}>Buy {t.strike.toLocaleString("en-IN")} {t.side}</span>
              <span className="ml-2 text-sm font-normal text-zinc-500">{t.expiry}</span>
            </p>
          ) : (
            <p className="text-xl font-semibold tracking-tight text-amber-400">No trade</p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {state === "loading" && <Pill tone="neutral">updating…</Pill>}
          {!data.market_open && <Pill tone="neutral">market closed</Pill>}
          {stale && <Pill tone="warn">chain {age} min old</Pill>}
          <Pill tone="warn">untested</Pill>
        </div>
      </div>

      <div className="px-5 py-4">
        {t ? (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Stat label={t.entry_source === "last" ? "Entry (last trade)" : "Entry (ask)"} value={premium(t.entry)} />
              <Stat label="Target" value={premium(t.target)} sub={`+${data.rules.target_pct}%`} />
              <Stat label="Stop-loss" value={premium(t.stop)} sub={`−${data.rules.stop_pct}%`} />
            </div>
            {t.entry == null && (
              <p className="mt-2 text-[12px] text-amber-300">NSE shows no price for this contract yet, so there is no entry, target or stop.</p>
            )}
            <p className="mt-4 text-sm leading-relaxed text-zinc-300">{t.rationale}</p>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-zinc-800/70 pt-3 sm:grid-cols-4">
              <Stat label="One lot" value={rs(t.lot_rs)} tone="muted" sub={t.lot_size ? `${t.lot_size} units` : undefined} />
              <Stat label="Charges" sub="both ways" value={rs(t.charges_rs)} tone="muted" />
              <Stat label="Breakeven" sub="at expiry" value={t.breakeven == null ? "–" : t.breakeven.toLocaleString("en-IN")} tone="muted" />
              <Stat label="IV" value={t.iv == null ? "–" : `${t.iv.toFixed(1)}%`} tone="muted" />
            </div>
          </>
        ) : (
          <p className="text-sm leading-relaxed text-zinc-300">{data.reason}</p>
        )}

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="PCR" value={data.inputs.pcr == null ? "–" : data.inputs.pcr.toFixed(2)} tone="muted" />
          <Stat label="Puts added" sub="near the money" value={fmtNum(data.inputs.put_oi_added)} tone="muted" />
          <Stat label="Calls added" sub="near the money" value={fmtNum(data.inputs.call_oi_added)} tone="muted" />
          <Stat label="Skew" value={data.inputs.skew_pct == null ? "–" : `${minus(data.inputs.skew_pct, 1)}%`} tone="muted"
                sub={data.inputs.near_from != null ? `${data.inputs.near_from}–${data.inputs.near_to}` : undefined} />
        </div>

        <div className="mt-4">
          <button type="button" onClick={() => setEditing((v) => !v)} aria-expanded={editing}
                  className="inline-flex min-h-8 items-center rounded-md border border-zinc-700 px-3 text-[12px] text-zinc-200 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
            {editing ? "Hide the rules" : custom ? "Your rules ▾" : "Change the rules ▾"}
          </button>
          {custom && (
            <button type="button" onClick={() => setStored("")}
                    className="ml-2 inline-flex min-h-8 items-center rounded-md px-3 text-[12px] text-indigo-300 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
              Back to the defaults
            </button>
          )}
          {editing && <RulesForm rules={data.rules} onApply={(r) => setStored(JSON.stringify(r))} />}
        </div>
      </div>

      <p className="border-t border-zinc-800 px-5 py-3 text-[11px] leading-relaxed text-zinc-500">
        <span className="font-semibold text-amber-300">Model-generated, not financial advice.</span>{" "}
        This trade comes from a fixed rule over NSE&apos;s live chain ({data.inputs.as_of || "time not given"}, expiry {data.inputs.expiry}):
        open interest added today near the money, PCR and IV, read the way traders commonly read them. The project
        has not tested whether that rule makes money, so treat it as a starting point you check, not a signal. The target and stop
        are fixed shares of the premium, not levels the chain gives. Kronos is not used: on its 2024–26 past check it called the
        direction no better than a coin and missed by more than assuming no change (its card below has its record).{" "}
        {data.default_rules
          ? data.logged ? "Today's trade is logged so it can be scored." : "The first trade of each session is logged so it can be scored."
          : "Trades from your own rules are not logged."}
      </p>
    </Panel>
  );
}

function RulesForm({ rules, onApply }: { rules: ChainTradeRules; onApply: (r: ChainTradeRules) => void }) {
  const [draft, setDraft] = useState<Record<string, string>>(
    Object.fromEntries(FIELDS.map((f) => [f.key, String(rules[f.key])])));
  const values = Object.fromEntries(FIELDS.map((f) => [f.key, Number(draft[f.key])])) as ChainTradeRules;
  const valid = FIELDS.every((f) => draft[f.key] !== "" && Number.isFinite(values[f.key]) && values[f.key] >= 0);
  return (
    <form className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); if (valid) onApply(values); }}>
      {FIELDS.map((f) => (
        <label key={f.key} htmlFor={`ctr-${f.key}`} className="flex flex-col gap-1 text-[11px] text-zinc-500">
          <span>{f.label} <span className="text-zinc-600">· {f.hint}</span></span>
          <input id={`ctr-${f.key}`} type="number" inputMode="decimal" min={0} step={f.step} value={draft[f.key]}
                 onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                 className="min-h-8 rounded-md border border-zinc-700 bg-zinc-950/60 px-2 font-mono text-sm tabular-nums text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60" />
        </label>
      ))}
      <div className="sm:col-span-2">
        <button type="submit" disabled={!valid}
                className="inline-flex min-h-8 items-center rounded-md border border-zinc-700 px-3 text-[12px] text-zinc-200 hover:bg-zinc-800 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
          Use these rules
        </button>
      </div>
    </form>
  );
}
