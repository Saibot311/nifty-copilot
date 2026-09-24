"use client";

import { useEffect, useState } from "react";
import type { EquityPoint, LiveTick, PaperReport, PaperSide, PaperTrade } from "@/lib/api";
import { journalRequest, subscribeToTick } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

/** A profit carries its sign; a balance does not. */
function rs(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
}

function money(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v < 0 ? "−" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
}

function pct(v: number | null | undefined) {
  return v == null ? "–" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
}

/** What trades have made, cumulatively, after each event. Money moved in or
 *  out does not move it: the balance used to be drawn here, and two
 *  withdrawals looked like a ₹50,000 loss. The dashed line is ₹0. */
function EquityCurve({ curve }: { curve: EquityPoint[] }) {
  if (curve.length < 2) return null;
  const W = 260, H = 54, pad = 3;
  const values = curve.map((p) => p.pnl_rs ?? 0);
  const lo = Math.min(...values, 0), hi = Math.max(...values, 0);
  const span = hi - lo || 1;
  const x = (i: number) => pad + (i / (curve.length - 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - 2 * pad);
  const path = curve.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.pnl_rs ?? 0).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  const up = last >= 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
      aria-label={`What paper trades have made over ${curve.length} events: ${Math.round(last)} rupees`}>
      <line x1={pad} x2={W - pad} y1={y(0)} y2={y(0)} stroke="#3f3f46" strokeWidth="1" strokeDasharray="3 3" />
      <path d={path} fill="none" stroke={up ? "#34d399" : "#fb7185"} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(curve.length - 1)} cy={y(last)} r="3.5" fill={up ? "#34d399" : "#fb7185"} stroke="#09090b" strokeWidth="1.5" />
    </svg>
  );
}

function Side({ title, side, hint }: { title: string; side: PaperSide; hint: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">{title}</div>
      <div className={`mt-0.5 font-mono text-lg tabular-nums ${side.total_per_lot_rs >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
        {side.closed ? rs(side.total_per_lot_rs) : "–"}
      </div>
      <div className="text-[11px] text-zinc-500">
        {side.closed} closed{side.open ? `, ${side.open} open` : ""}
        {side.avg_net_pct != null && ` · avg ${pct(side.avg_net_pct)}`}
        {side.win_rate != null && ` · won ${Math.round(side.win_rate * 100)}%`}
      </div>
      <div className="text-[11px] text-zinc-600">{hint}</div>
    </div>
  );
}

function Row({ t, mark }: { t: PaperTrade; mark?: number }) {
  const live = t.status === "OPEN";
  return (
    <tr className="border-t border-zinc-800/60">
      <td className="py-1.5 pr-3">
        <span className="text-zinc-200">{t.label}</span>
        <span className="block text-[10px] text-zinc-600">
          signal {t.signal_date} · bought {t.entry_date} at ₹{t.entry_premium}
        </span>
      </td>
      <td className="hidden py-1.5 pr-3 font-mono text-[11px] tabular-nums text-zinc-400 sm:table-cell">
        {t.strike} {t.option_type}
        <span className="block text-[10px] text-zinc-600">exp {t.expiry}</span>
      </td>
      <td className="hidden py-1.5 pr-3 font-mono text-[11px] tabular-nums text-zinc-400 sm:table-cell">
        {live ? (mark ?? t.mark_premium) != null ? `₹${mark ?? t.mark_premium}` : "–" : `₹${t.exit_premium}`}
        <span className="block text-[10px] text-zinc-600">
          {live ? (mark != null ? "live" : `marked ${t.mark_date ?? "—"}`) : `sold ${t.exit_date}`}
        </span>
      </td>
      <td className={`py-1.5 pr-3 text-right font-mono text-xs tabular-nums ${(t.pnl?.net_pct ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
        {t.pnl ? rs(t.pnl.profit_rs) : "–"}
        <span className="block text-[10px] text-zinc-600">
          {t.pnl ? `${pct(t.pnl.net_pct)} · ${t.pnl.lots} lot${t.pnl.lots === 1 ? "" : "s"}` : ""}
        </span>
      </td>
      <td className="py-1.5 text-right">
        <Pill tone={live ? "info" : (t.pnl?.profit_rs ?? 0) >= 0 ? "good" : "bad"}>{live ? "open" : "closed"}</Pill>
      </td>
    </tr>
  );
}

function Funds({ account, onChange }: { account: PaperReport["account"]; onChange: () => void }) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const r = await journalRequest<{ allocated_rs: number }>("/api/paper/funds", "POST",
      { amount: Number(amount), note: "from the dashboard" });
    setBusy(false);
    if (r.error) { setErr(r.error); return; }
    setAmount("");
    onChange();
  }

  return (
    <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2 border-t border-zinc-800/60 pt-3">
      <label className="flex flex-col gap-1 text-[11px] text-zinc-500">
        Allocate to the paper book (₹) — negative to take it back
        <input
          id="paper-funds" type="number" step="any" required value={amount}
          onChange={(e) => setAmount(e.target.value)} placeholder="100000"
          className="w-40 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-indigo-500/60 focus:outline-none"
        />
      </label>
      <button type="submit" disabled={busy}
        className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-indigo-500/60 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
        {busy ? "Saving…" : "Set funds"}
      </button>
      <span className="text-[11px] text-zinc-600">
        Paper money only — no account is touched. At most {Math.round(account.max_per_trade_share * 100)}% of it
        ({money(account.max_per_trade_rs)}) goes into any one position, in whole lots of 65.
      </span>
      {err && <span className="text-xs text-rose-300">{err}</span>}
    </form>
  );
}

export function PaperCard({ data: initial }: { data: PaperReport | null }) {
  const [data, setData] = useState(initial);
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    journalRequest<PaperReport>("/api/paper").then((r) => { if (alive && r.data) setData(r.data); });
    return () => { alive = false; };
  }, [version, initial]);

  // While the market is open the open positions are worth what they trade at
  // now, not what they closed at last night.
  useEffect(() => subscribeToTick(setTick), []);

  if (!data) return <Offline what="Paper observation" />;
  const { summary, trades, account } = data;
  const benchmark = data.benchmark ?? [];
  const live = tick?.paper && tick.market?.is_open ? tick.paper : null;
  const enough = summary.patterns.closed >= summary.sessions_needed_before_this_means_anything;

  return (
    <Panel className="p-4">
      <p className="mb-3 text-[11px] text-zinc-500">
        {summary.observing_since
          ? `Observing since ${summary.observing_since}. `
          : `Nothing opened yet; observation starts from ${summary.started}. `}
        {summary.book_closed ?? summary.patterns.closed + summary.best_read.closed} of the book&apos;s trades closed, of the ~
        {summary.sessions_needed_before_this_means_anything} it takes before any of these totals mean anything.
      </p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">Paper book</div>
          <div className="mt-0.5 font-mono text-lg tabular-nums text-zinc-100">
            {money((live ?? account).equity_rs)}
            {live && <span className="ml-1.5 text-[10px] uppercase tracking-wider text-emerald-400">live</span>}
          </div>
          <div className="text-[11px] text-zinc-500">
            {money(account.allocated_rs)} allocated · {money((live ?? account).cash_rs)} cash
          </div>
          {account.allocated_rs > 0 && (
            <div className={`text-[11px] ${((live ?? account).return_pct ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {pct((live ?? account).return_pct)} since funding
            </div>
          )}
        </div>
        <Side title="Patterns, on paper" side={summary.patterns} hint="setups that formed" />
        <Side title="Best reading" side={summary.best_read} hint="nothing formed → one 2% in-the-money option, strongest signal" />
        <Side title="No signal (control)" side={summary.control} hint="one lot each way, weekly — measured beside the book, not held in it" />
      </div>
      {data.equity_curve.length > 1 && (
        <div className="mt-4 rounded-lg bg-zinc-950/50 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">The book, win by win</span>
            <span className="font-mono text-[11px] tabular-nums text-zinc-500">
              made {rs(data.objective.profit_rs)} · best {rs(data.objective.pnl_high_rs)}
              {data.objective.below_high_water_rs > 0 && ` · ${rs(-data.objective.below_high_water_rs)} from it`}
            </span>
          </div>
          <EquityCurve curve={data.equity_curve} />
          <p className="text-[11px] leading-relaxed text-zinc-500">
            <span className="text-zinc-300">Goal: </span>{data.objective.goal} {data.objective.sizing_note}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-zinc-600">{data.objective.containment}</p>
        </div>
      )}

      {account.allocated_rs === 0 && (
        <p className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-200">
          No paper funds allocated yet, so nothing can be sized or opened. Set an amount below — it is paper money
          and no account is touched.
        </p>
      )}

      <p className="mt-4 text-[11px] text-zinc-500">
        The book takes <span className="text-zinc-300">one position a session</span>, in one direction. When
        several setups form, the one with the strongest holdout evidence takes it and the rest are passed over.
      </p>

      {trades.length > 0 ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
              <tr>
                <th className="pb-2 font-medium">Setup</th>
                <th className="hidden pb-2 font-medium sm:table-cell">Contract</th>
                <th className="hidden pb-2 font-medium sm:table-cell">Now</th>
                <th className="pb-2 text-right font-medium">Per lot</th>
                <th className="pb-2 text-right font-medium">State</th>
              </tr>
            </thead>
            <tbody>{trades.slice(0, 20).map((t) => <Row key={t.id} t={t} mark={tick?.marks?.[String(t.id)]} />)}</tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 text-xs text-zinc-500">
          Nothing opened yet. The first positions open the evening after a setup forms, once that session&apos;s
          option prices are published — starting from {summary.started}.
        </p>
      )}

      {data.last_decision && (
        <div className="mt-3 rounded-lg bg-zinc-950/50 p-3 text-[11px] leading-relaxed text-zinc-400">
          <span className="text-zinc-300">Last evening</span>{" "}
          <span className="font-mono tabular-nums text-zinc-500">
            (signal {data.last_decision.signal_session} → entry {data.last_decision.entry_session}):
          </span>{" "}
          {data.last_decision.opened.length > 0
            ? `opened ${data.last_decision.opened.join(", ")}.`
            : "nothing opened."}
          {data.last_decision.note && <> {data.last_decision.note}.</>}
          {data.last_decision.skipped.map((why) => (
            <span key={why} className="block text-amber-200/80">Skipped — {why}</span>
          ))}
          {data.last_decision.passed_over.length > 0 && (
            <span className="block text-zinc-500">
              Also formed, passed over (one position a session): {data.last_decision.passed_over.join(", ")}
            </span>
          )}
        </div>
      )}

      {benchmark.length > 0 && (
        <div className="mt-4 border-t border-zinc-800/60 pt-3">
          <div className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">Yardstick — not in the book</div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-600">
            A call and a put bought weekly with no signal, priced on the same real premiums. It spends none of
            the allocated money, moves none of the equity above, and cannot take a session&apos;s slot. It is
            here because a result with nothing to compare it against means nothing.
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
                <tr>
                  <th className="pb-2 font-medium">Setup</th>
                  <th className="hidden pb-2 font-medium sm:table-cell">Contract</th>
                  <th className="hidden pb-2 font-medium sm:table-cell">Now</th>
                  <th className="pb-2 text-right font-medium">Per lot</th>
                  <th className="pb-2 text-right font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {benchmark.slice(0, 10).map((t) => <Row key={t.id} t={t} mark={tick?.marks?.[String(t.id)]} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Funds account={account} onChange={() => setVersion((v) => v + 1)} />
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        {data.note}
        {enough ? "" : ` About ${summary.sessions_needed_before_this_means_anything} closed trades are needed before any of these totals mean anything.`}
      </p>
    </Panel>
  );
}
