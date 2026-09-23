import type { ForwardEntry, ForwardLog } from "@/lib/api";
import { Offline, Panel, Pill, Stat, fmtPct } from "./ui";

const ACTION: Record<ForwardEntry["action"], { label: string; tone: "good" | "bad" | "neutral" }> = {
  CONSIDER_CALL: { label: "CALL", tone: "good" },
  CONSIDER_PUT: { label: "PUT", tone: "bad" },
  NO_TRADE: { label: "NO TRADE", tone: "neutral" },
};

function Move({ entry, h }: { entry: ForwardEntry; h: "1d" | "5d" | "10d" }) {
  const o = entry.outcomes[h];
  if (!o) return <span className="text-zinc-700">pending</span>;
  const v = o.trade_return_pct ?? o.index_move_pct;
  return (
    <span className={v >= 0 ? "text-emerald-400" : "text-rose-400"}>{fmtPct(v)}</span>
  );
}

export function ForwardLogCard({ log }: { log: ForwardLog | null }) {
  if (!log) return <Offline what="Forward log" />;
  const { summary, entries } = log;

  return (
    <Panel className="p-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Days logged"
          value={summary.days_logged}
          sub={[summary.logging_since ? `since ${summary.logging_since}` : null,
                summary.days_excluded_recorded_late ? `${summary.days_excluded_recorded_late} not counted` : null]
                .filter(Boolean).join(" · ") || undefined}
        />
        <Stat
          label="Calls / puts / no trade"
          value={`${summary.by_action.CONSIDER_CALL} / ${summary.by_action.CONSIDER_PUT} / ${summary.by_action.NO_TRADE}`}
        />
        <Stat label="Completed trades (10d)" value={summary.completed_trades_10d} />
        <Stat
          label="Avg 10d return"
          value={summary.avg_return_10d_pct != null ? fmtPct(summary.avg_return_10d_pct) : "–"}
          tone={summary.avg_return_10d_pct == null ? "muted" : summary.avg_return_10d_pct >= 0 ? "good" : "bad"}
          sub={summary.completed_trades_10d
            ? `over ${summary.completed_trades_10d} completed · hit rate ${(summary.hit_rate_10d ?? 0) * 100}%`
            : "no completed trades yet — this needs months, not days"}
        />
      </div>

      {entries.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-600">
              <tr>
                <th className="pb-2 font-medium">Close of</th>
                <th className="pb-2 font-medium">Verdict</th>
                <th className="hidden pb-2 font-medium sm:table-cell">Regime</th>
                <th className="hidden pb-2 text-right font-medium sm:table-cell">1d</th>
                <th className="hidden pb-2 text-right font-medium sm:table-cell">5d</th>
                <th className="pb-2 text-right font-medium">10d</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums text-zinc-300">
              {entries.slice(0, 15).map((e) => (
                <tr key={e.as_of} className={`border-t border-zinc-800/60 ${e.recorded_late ? "text-zinc-600" : ""}`}>
                  <td className="py-1.5">
                    {e.as_of}
                    {e.recorded_late && (
                      <span className="ml-1.5 font-sans text-[10px] text-amber-400/80" title="Written after its entry session had already opened, so the outcome already existed. Kept for the record, left out of the totals.">
                        not counted
                      </span>
                    )}
                  </td>
                  <td className="py-1.5">
                    <Pill tone={ACTION[e.action].tone}>{ACTION[e.action].label}</Pill>
                  </td>
                  <td className="hidden py-1.5 text-zinc-500 sm:table-cell">{e.regime}</td>
                  {(["1d", "5d", "10d"] as const).map((h) => (
                    <td
                      key={h}
                      // 10d is the horizon the verdicts are judged on; the
                      // other two are detail, and a phone hides detail
                      // rather than scrolling sideways (DESIGN.md §8).
                      className={`py-1.5 text-right ${h === "10d" ? "" : "hidden sm:table-cell"}`}
                    >
                      <Move entry={e} h={h} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[10px] text-zinc-600">
            For CALL/PUT rows the columns are the trade&apos;s return; for NO TRADE they show what the
            index did while the system stood aside.
          </p>
        </div>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">{log.note}</p>
    </Panel>
  );
}
