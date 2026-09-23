"use client";

import { useEffect, useState } from "react";
import type { LiveTick, PaperReport, PaperSide, PaperTrade } from "@/lib/api";
import { fetchTick, journalRequest } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

/** A profit carries its sign; a balance does not. */
function rs(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
}

function money(v: number | null | undefined) {
  if (v == null) return "–";
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

function pct(v: number | null | undefined) {
  return v == null ? "–" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
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
      <td className="py-1.5 pr-3 font-mono text-[11px] tabular-nums text-zinc-400">
        {t.strike} {t.option_type}
        <span className="block text-[10px] text-zinc-600">exp {t.expiry}</span>
      </td>
      <td className="py-1.5 pr-3 font-mono text-[11px] tabular-nums text-zinc-400">
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
        className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-indigo-500/60 disabled:opacity-50">
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
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const run = async () => {
      const r = await fetchTick();
      if (!alive) return;
      if (r.data) setTick(r.data);
      timer = setTimeout(run, r.data?.market?.is_open ? 3000 : 60000);
    };
    run();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  if (!data) return <Offline what="Paper observation" />;
  const { summary, trades, account } = data;
  const live = tick?.paper && tick.market?.is_open ? tick.paper : null;
  const enough = summary.patterns.closed >= summary.sessions_needed_before_this_means_anything;

  return (
    <Panel className="p-4">
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
        <Side title="Best reading" side={summary.best_read} hint="when nothing formed — no proven edge" />
        <Side title="No signal (control)" side={summary.control} hint="one call and one put a week" />
      </div>
      {account.allocated_rs === 0 && (
        <p className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-200">
          No paper funds allocated yet, so nothing can be sized or opened. Set an amount below — it is paper money
          and no account is touched.
        </p>
      )}

      {trades.length > 0 ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
              <tr>
                <th className="pb-2 font-medium">Setup</th>
                <th className="pb-2 font-medium">Contract</th>
                <th className="pb-2 font-medium">Now</th>
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

      <Funds account={account} onChange={() => setVersion((v) => v + 1)} />
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        {data.note}
        {enough ? "" : ` About ${summary.sessions_needed_before_this_means_anything} closed trades are needed before any of these totals mean anything.`}
      </p>
    </Panel>
  );
}
