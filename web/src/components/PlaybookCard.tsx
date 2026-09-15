import type { PlaybookEntry } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

const TONE: Record<string, "good" | "warn" | "bad"> = {
  APPROVED: "good",
  CONDITIONAL: "warn",
  REJECTED: "bad",
};

export function PlaybookCard({ entries }: { entries: PlaybookEntry[] | null }) {
  if (!entries) return <Offline what="Strategy playbook" />;

  if (entries.length === 0) {
    return (
      <Panel className="p-4 text-sm text-zinc-500">
        No strategy has been through walk-forward validation yet.
      </Panel>
    );
  }

  const order = { APPROVED: 0, CONDITIONAL: 1, REJECTED: 2 };
  const rows = [...entries].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));

  return (
    <Panel className="p-4">
      <div className="mb-3 text-xs text-zinc-500">
        Persistent record of every strategy that has been through Phase 8 walk-forward validation —
        a real table, not a live recomputation. {entries.length} strategies checked so far.
      </div>
      <div className="flex flex-col gap-2">
        {rows.map((e) => (
          <div key={e.strategy} className="rounded-lg bg-zinc-950/60 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-zinc-200">{e.label}</span>
              <div className="flex items-center gap-2">
                {e.num_trades != null && (
                  <span className="font-mono text-[11px] text-zinc-500 tabular-nums">
                    {e.num_trades}t · {e.expectancy_pct != null ? `${e.expectancy_pct > 0 ? "+" : ""}${e.expectancy_pct}%` : "–"}
                  </span>
                )}
                <Pill tone={TONE[e.status] ?? "warn"}>{e.status}</Pill>
              </div>
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-zinc-500">{e.reason}</p>
            <p className="mt-1 text-[10px] text-zinc-700">
              checked {new Date(e.checked_at).toLocaleString("en-IN")}
            </p>
          </div>
        ))}
      </div>
    </Panel>
  );
}
