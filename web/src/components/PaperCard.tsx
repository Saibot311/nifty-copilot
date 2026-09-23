import type { PaperReport, PaperSide, PaperTrade } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

function rs(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
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

function Row({ t }: { t: PaperTrade }) {
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
        {live ? (t.mark_premium != null ? `₹${t.mark_premium}` : "–") : `₹${t.exit_premium}`}
        <span className="block text-[10px] text-zinc-600">
          {live ? `marked ${t.mark_date ?? "—"}` : `sold ${t.exit_date}`}
        </span>
      </td>
      <td className={`py-1.5 pr-3 text-right font-mono text-xs tabular-nums ${(t.pnl?.net_pct ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
        {t.pnl ? `${rs(t.pnl.profit_per_lot_rs)}` : "–"}
        <span className="block text-[10px] text-zinc-600">{t.pnl ? pct(t.pnl.net_pct) : ""}</span>
      </td>
      <td className="py-1.5 text-right">
        <Pill tone={live ? "info" : t.pnl && t.pnl.net_pct >= 0 ? "good" : "bad"}>{live ? "open" : "closed"}</Pill>
      </td>
    </tr>
  );
}

export function PaperCard({ data }: { data: PaperReport | null }) {
  if (!data) return <Offline what="Paper observation" />;
  const { summary, trades } = data;
  const enough = summary.patterns.closed >= summary.sessions_needed_before_this_means_anything;

  return (
    <Panel className="p-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Side title="Patterns, on paper" side={summary.patterns} hint="setups that formed, at real premiums" />
        <Side title="No signal (control)" side={summary.control} hint="one call and one put a week" />
        <div>
          <div className="text-[11px] uppercase tracking-[0.1em] text-zinc-500">Observing since</div>
          <div className="mt-0.5 font-mono text-lg tabular-nums text-zinc-100">{summary.observing_since ?? "—"}</div>
          <div className="text-[11px] text-zinc-500">
            {enough ? "enough closed trades to read" : `needs about ${summary.sessions_needed_before_this_means_anything} closed trades before it means anything`}
          </div>
        </div>
      </div>

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
            <tbody>{trades.slice(0, 20).map((t) => <Row key={t.id} t={t} />)}</tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 text-xs text-zinc-500">
          Nothing opened yet. The first positions open the evening after a setup forms, once that session&apos;s
          option prices are published — starting from {summary.started}.
        </p>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">{data.note}</p>
    </Panel>
  );
}
