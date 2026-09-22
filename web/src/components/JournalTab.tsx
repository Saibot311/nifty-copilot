"use client";

import { useEffect, useState } from "react";
import { journalRequest, type JournalDecision, type JournalReport, type JournalRow } from "@/lib/api";
import { Panel, Pill, SectionLabel } from "./ui";

const inputCls =
  "w-full rounded-md border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-indigo-500/60 focus:outline-none";

function rs(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN")}`;
}

const SYSTEM_LABEL: Record<string, string> = { NO_TRADE: "No trade", CONSIDER_CALL: "Consider call", CONSIDER_PUT: "Consider put" };

function today() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

type Form = {
  trade_date: string; decision: JournalDecision; underlying: string; option_type: string; strike: string;
  expiry: string; quantity: string; entry_premium: string; reason: string;
};

const EMPTY: Form = { trade_date: today(), decision: "SKIPPED", underlying: "NIFTY", option_type: "CE", strike: "",
  expiry: "", quantity: "", entry_premium: "", reason: "" };

export function JournalTab() {
  const [report, setReport] = useState<JournalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [saving, setSaving] = useState(false);

  const [version, setVersion] = useState(0);
  const load = () => setVersion((v) => v + 1);

  useEffect(() => {
    let alive = true;
    journalRequest<JournalReport>("/api/journal").then((r) => {
      if (!alive) return;
      if (r.data) setReport(r.data);
      else setError(r.error ?? "Could not load the journal.");
    });
    return () => { alive = false; };
  }, [version]);

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const took = form.decision === "TOOK";
    const r = await journalRequest<{ id: number }>("/api/journal", "POST", {
      trade_date: form.trade_date, decision: form.decision, reason: form.reason || null,
      ...(took ? {
        underlying: form.underlying, option_type: form.option_type, strike: Number(form.strike),
        expiry: form.expiry, quantity: Number(form.quantity), entry_premium: Number(form.entry_premium),
      } : {}),
    });
    setSaving(false);
    if (r.error) { setError(r.error); return; }
    setForm({ ...EMPTY, trade_date: form.trade_date });
    load();
  }

  const s = report?.summary;
  const took = form.decision === "TOOK";

  return (
    <>
      <section>
        <SectionLabel hint="what you did, next to what the system said">Your trade journal</SectionLabel>
        <Panel className="p-4">
          <form onSubmit={submit} className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <label className="flex flex-col gap-1 text-xs text-zinc-400">Session
                <input id="j-date" type="date" required value={form.trade_date} onChange={set("trade_date")} className={inputCls} />
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-400">What you did
                <select id="j-decision" value={form.decision} onChange={set("decision")} className={inputCls}>
                  <option value="SKIPPED">Stayed out</option>
                  <option value="WAITED">Waited / watching</option>
                  <option value="TOOK">Bought an option</option>
                </select>
              </label>
              {took && (
                <>
                  <label className="flex flex-col gap-1 text-xs text-zinc-400">Index
                    <select id="j-underlying" value={form.underlying} onChange={set("underlying")} className={inputCls}>
                      {["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY"].map((u) => <option key={u}>{u}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-400">Bought
                    <select id="j-type" value={form.option_type} onChange={set("option_type")} className={inputCls}>
                      <option value="CE">Call (CE)</option>
                      <option value="PE">Put (PE)</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-400">Strike
                    <input id="j-strike" type="number" step="any" min="0" required value={form.strike} onChange={set("strike")} className={inputCls} placeholder="23400" />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-400">Expiry
                    <input id="j-expiry" type="date" required value={form.expiry} onChange={set("expiry")} className={inputCls} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-400">Quantity (units)
                    <input id="j-qty" type="number" min="1" step="1" required value={form.quantity} onChange={set("quantity")} className={inputCls} placeholder="65" />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-400">Premium paid (₹)
                    <input id="j-entry" type="number" step="any" min="0" required value={form.entry_premium} onChange={set("entry_premium")} className={inputCls} placeholder="120.5" />
                  </label>
                </>
              )}
            </div>
            <label className="flex flex-col gap-1 text-xs text-zinc-400">Why (in your own words — this is the part you&apos;ll learn from)
              <textarea id="j-reason" rows={2} value={form.reason} onChange={set("reason")} maxLength={2000} className={inputCls}
                placeholder="e.g. System said no trade; I agreed because nothing formed." />
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" disabled={saving}
                className="rounded-md bg-indigo-500/90 px-3.5 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">
                {saving ? "Saving…" : "Add to journal"}
              </button>
              <span className="text-[11px] text-zinc-500">The system&apos;s verdict for that session is filled in from the forward log, not typed.</span>
              {error && <span className="text-xs text-rose-300">{error}</span>}
            </div>
          </form>
        </Panel>
      </section>

      {s && (
        <section>
          <SectionLabel hint="after the same costs as every backtest">How it&apos;s going</SectionLabel>
          <Panel className="p-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Tile label="Entries" value={`${s.entries}`} sub={`${s.by_decision.TOOK} took · ${s.by_decision.SKIPPED} stayed out · ${s.by_decision.WAITED} waited`} />
              <Tile label="Closed trades, net" value={rs(s.net_rs)} sub={`${s.closed_trades} closed · ${s.open_trades} open${s.win_rate != null ? ` · won ${Math.round(s.win_rate * 100)}%` : ""}`} />
              <Tile label="When you followed the system" value={rs(s.followed_system.net_rs)} sub={`${s.followed_system.trades} closed trade${s.followed_system.trades === 1 ? "" : "s"}`} />
              <Tile label="When you overrode it" value={rs(s.overrode_system.net_rs)} sub={`${s.overrode_system.trades} closed trade${s.overrode_system.trades === 1 ? "" : "s"}`} />
            </div>
            <p className="mt-3 text-xs leading-relaxed text-zinc-500">{report!.note}</p>
          </Panel>
        </section>
      )}

      {report && report.entries.length > 0 && (
        <section>
          <SectionLabel>Entries</SectionLabel>
          <div className="flex flex-col gap-2">
            {report.entries.map((e) => <Entry key={e.id} e={e} onChange={load} />)}
          </div>
        </section>
      )}
      {report && report.entries.length === 0 && (
        <p className="text-sm text-zinc-500">No entries yet. Log today&apos;s decision — including &quot;stayed out&quot; — every session.
          Skipped days matter as much as trades: they&apos;re how the journal learns whether following the system helps.</p>
      )}
    </>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">{label}</div>
      <div className="mt-0.5 font-mono text-lg tabular-nums text-zinc-100">{value}</div>
      <div className="text-[11px] text-zinc-500">{sub}</div>
    </div>
  );
}

function Entry({ e, onChange }: { e: JournalRow; onChange: () => void }) {
  const [exit, setExit] = useState("");
  const [exitDate, setExitDate] = useState(today());
  const [err, setErr] = useState<string | null>(null);
  const open = e.decision === "TOOK" && e.exit_premium == null;

  async function close(ev: React.FormEvent) {
    ev.preventDefault();
    const r = await journalRequest(`/api/journal/${e.id}/close`, "POST", { exit_premium: Number(exit), exit_date: exitDate });
    if (r.error) setErr(r.error); else onChange();
  }
  async function remove() {
    if (!window.confirm("Delete this journal entry? This can't be undone.")) return;
    const r = await journalRequest(`/api/journal/${e.id}`, "DELETE");
    if (r.error) setErr(r.error); else onChange();
  }

  const what = e.decision === "TOOK"
    ? `Bought ${e.underlying} ${e.strike} ${e.option_type} (exp ${e.expiry}) × ${e.quantity} at ₹${e.entry_premium}`
    : e.decision === "SKIPPED" ? "Stayed out" : "Waited / watching";

  return (
    <Panel className="p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-mono text-xs text-zinc-500">{e.trade_date}</span>
        <span className="text-zinc-200">{what}</span>
        <span className="text-[11px] text-zinc-500">System: {e.system_action ? SYSTEM_LABEL[e.system_action] ?? e.system_action : "not recorded that day"}</span>
        {e.followed_system != null && (
          <Pill tone={e.followed_system ? "info" : "warn"}>{e.followed_system ? "Followed" : "Overrode"}</Pill>
        )}
        {e.pnl && <span className={`font-mono text-sm tabular-nums ${e.pnl.net_rs >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{rs(e.pnl.net_rs)} ({e.pnl.return_pct}%)</span>}
        <button onClick={remove} className="ml-auto text-[11px] text-zinc-600 hover:text-rose-300">Delete</button>
      </div>
      {e.reason && <p className="mt-1 text-xs text-zinc-400">{e.reason}</p>}
      {e.pnl && <p className="mt-1 text-[11px] text-zinc-500">Sold at ₹{e.exit_premium} on {e.exit_date} · gross {rs(e.pnl.gross_rs)}, costs {rs(-e.pnl.costs_rs)}</p>}
      {open && (
        <form onSubmit={close} className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[11px] text-zinc-500">Sold at (₹)
            <input id={`j-exit-${e.id}`} type="number" step="any" min="0" required value={exit} onChange={(x) => setExit(x.target.value)} className={`${inputCls} w-28`} />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-zinc-500">On
            <input id={`j-exitdate-${e.id}`} type="date" required value={exitDate} onChange={(x) => setExitDate(x.target.value)} className={`${inputCls} w-40`} />
          </label>
          <button type="submit" className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-indigo-500/60">Close trade</button>
          {err && <span className="text-xs text-rose-300">{err}</span>}
        </form>
      )}
    </Panel>
  );
}
