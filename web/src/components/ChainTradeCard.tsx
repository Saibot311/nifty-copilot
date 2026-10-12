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
const PLAN_KEY = "chain_trade_plan";
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

type Plan = { capital: number; risk_pct: number };

function parsePlan(raw: string): Plan | null {
  if (!raw) return null;
  try {
    const p = JSON.parse(raw) as Partial<Plan>;
    return typeof p.capital === "number" && p.capital > 0 && typeof p.risk_pct === "number" ? (p as Plan) : null;
  } catch { return null; }
}

function parseRules(raw: string): Partial<ChainTradeRules> | null {
  if (!raw) return null;
  try { return JSON.parse(raw) as Partial<ChainTradeRules>; } catch { return null; }
}

export function ChainTradeCard({ initial }: { initial: ChainTrade | null }) {
  const [stored, setStored] = useStored(RULES_KEY, "");
  const custom = parseRules(stored);
  const [storedPlan, setStoredPlan] = useStored(PLAN_KEY, "");
  const plan = parsePlan(storedPlan);
  // The answer for your own rules, tagged with the request it answers: the
  // rules, and the page render it was asked for with.
  const [mine, setMine] = useState<{ key: string; data: ChainTrade | null } | null>(null);
  const [editing, setEditing] = useState(false);
  // Your own rules or your own capital means the page's default answer is not the one wanted.
  const own = !!custom || !!plan;
  const prefix = `${stored}|${storedPlan}|`;
  const key = `${prefix}${initial?.computed_at ?? ""}`;

  // Rules of your own are asked for when set and again whenever the page
  // refreshes (a new `initial`); the defaults come with the page.
  useEffect(() => {
    const rules = parseRules(stored);
    const p = parsePlan(storedPlan);
    if (!rules && !p) return;
    let alive = true;
    fetchChainTrade(rules ?? undefined, p ?? undefined).then((r) => { if (alive) setMine({ key, data: r.data }); });
    return () => { alive = false; };
  }, [stored, storedPlan, key]);

  const answered = mine?.key === key;
  const state = !own ? "idle" : !answered ? "loading" : mine.data ? "idle" : "failed";
  // While a refresh for your rules is out, the last answer for them stays up.
  const data = own ? (mine?.key.startsWith(prefix) ? mine.data : null) : initial;
  if (!initial && !own) {
    return <Offline what="The option-chain trade" why="NSE's option chain did not answer, so there is nothing to read the trade from." />;
  }
  if (own && state === "failed") {
    return <Offline what="The option-chain trade" why="The API did not answer for your rules or capital. Reset them, or reload." />;
  }
  if (!data) {
    return (
      <Panel className="p-5">
        <p className="text-sm text-zinc-500" role="status">Reading the chain with your settings…</p>
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
        <PlanForm plan={plan} onChange={(p) => setStoredPlan(p ? JSON.stringify(p) : "")} />
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
            {plan && <YourPlan t={t} />}
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

const inr0 = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const num0 = (v: number) => Math.round(v).toLocaleString("en-IN");

/** Capital and the share of it to risk, remembered per viewer. Edits are held
 *  in the boxes and sent on after ~400 ms of quiet, so typing is not a request
 *  per keystroke. Empty capital clears the plan. */
function PlanForm({ plan, onChange }: { plan: Plan | null; onChange: (p: Plan | null) => void }) {
  const [cap, setCap] = useState(plan ? String(plan.capital) : "");
  const [risk, setRisk] = useState(plan ? String(plan.risk_pct) : "2");
  useEffect(() => {
    const c = Number(cap), r = Number(risk);
    const next: Plan | null = cap !== "" && c > 0 && r >= 0.1 && r <= 20 ? { capital: c, risk_pct: r } : null;
    if (cap !== "" && !next) return; // half-typed or out of range: wait
    if (next?.capital === plan?.capital && next?.risk_pct === plan?.risk_pct) return;
    if (!next && !plan) return;
    const id = setTimeout(() => onChange(next), 400);
    return () => clearTimeout(id);
  }, [cap, risk]); // eslint-disable-line react-hooks/exhaustive-deps
  const badRisk = !(Number(risk) >= 0.1 && Number(risk) <= 20);
  const box = "min-h-9 w-full min-w-0 rounded-md border border-zinc-700 bg-zinc-950/60 px-2 font-mono text-sm tabular-nums text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60";
  return (
    <div className="mb-4 grid grid-cols-2 gap-3">
      <label htmlFor="ctr-capital" className="flex min-w-0 flex-col gap-1 text-[11px] text-zinc-500">
        <span>Your capital (₹)</span>
        <input id="ctr-capital" type="number" inputMode="decimal" min={0} step={1000} value={cap} placeholder="e.g. 50000"
               onChange={(e) => setCap(e.target.value)} className={box} />
      </label>
      <label htmlFor="ctr-risk" className="flex min-w-0 flex-col gap-1 text-[11px] text-zinc-500">
        <span>Risk per trade (%)</span>
        <input id="ctr-risk" type="number" inputMode="decimal" min={0.1} max={20} step={0.5} value={risk}
               aria-invalid={badRisk} onChange={(e) => setRisk(e.target.value)} className={box} />
      </label>
      {badRisk && <p className="col-span-2 text-[11px] text-amber-300">Risk per trade must be between 0.1% and 20%.</p>}
    </div>
  );
}

/** The plan in beginner words. Every figure is the API's; this only formats. */
function YourPlan({ t }: { t: NonNullable<ChainTrade["trade"]> }) {
  const s = t.sizing, lv = t.levels;
  if (!s) {
    return <p className="mt-4 text-[12px] text-amber-300">No size can be worked out yet: NSE shows no price for this contract.</p>;
  }
  const steps: string[] = [];
  if (lv) {
    steps.push(lv.entry_condition + (lv.entry_max_text ? `. ${lv.entry_max_text}` : ""));
    if (lv.exit_target_text) steps.push(lv.exit_target_text);
    if (lv.exit_stop_text) steps.push(lv.exit_stop_text + (lv.invalidation_text ? `, ${lv.invalidation_text}` : ""));
    steps.push(lv.time_exit);
  }
  return (
    <section aria-label="Your plan" className="mt-4 rounded-lg border border-zinc-700/70 bg-zinc-900/40 p-4">
      <h3 className="text-sm font-semibold text-zinc-100">Your plan</h3>
      {s.lots === 0 ? (
        <p className="mt-2 text-sm leading-relaxed text-amber-300">{s.note}</p>
      ) : (
        <>
          <p className="mt-2 text-sm leading-relaxed text-zinc-300">
            Buy <span className="font-semibold text-zinc-100">{s.lots} {s.lots === 1 ? "lot" : "lots"}</span> ({num0(s.quantity)} units),
            kept to {s.limited_by === "risk" ? `the ${s.risk_pct}% you chose to risk` : "what your money buys"}.
          </p>
          <div className="mt-3 grid grid-cols-3 gap-3">
            <Stat label="You put in" value={inr0(s.deployed_rs)} tone="muted" />
            <Stat label="Loss at stop" value={`−${inr0(s.max_loss_rs)}`} tone="bad" sub="with charges" />
            <Stat label="Gain at target" value={`+${inr0(s.profit_at_target_rs)}`} tone="good" sub="after charges" />
          </div>
        </>
      )}
      {steps.length > 0 && (
        <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-zinc-300">
          {steps.map((x, i) => <li key={i}>{x}</li>)}
        </ol>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        NIFTY levels are a guide worked out from the option&apos;s delta; the premium can differ as time passes.
      </p>
    </section>
  );
}
