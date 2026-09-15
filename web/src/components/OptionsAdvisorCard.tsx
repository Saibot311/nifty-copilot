import type { OptionsAdvice } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

export function OptionsAdvisorCard({ advice }: { advice: OptionsAdvice | null }) {
  if (!advice) return <Offline what="Options helper" />;

  if (!advice.actionable_today) {
    return (
      <Panel className="p-4">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
          EMA Pullback → options idea
        </div>
        <div className="rounded-lg bg-zinc-950/60 p-3 text-sm text-zinc-400">
          {advice.message}
        </div>
        {advice.recent_signal_dates.length > 0 && (
          <div className="mt-3 text-xs text-zinc-600">
            Last fired: {advice.recent_signal_dates[advice.recent_signal_dates.length - 1]}
          </div>
        )}
      </Panel>
    );
  }

  return (
    <Panel emphasis="raised" className="border-emerald-500/30 bg-emerald-500/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-400">
          EMA Pullback → Options Idea (as of {advice.as_of})
        </div>
        <Pill tone="good">{advice.direction}</Pill>
      </div>

      <p className="mt-3 text-sm text-zinc-300">{advice.rationale}</p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg bg-zinc-950/60 p-3">
          <div className="text-xs font-medium text-zinc-500 mb-1">Strike</div>
          <div className="text-sm text-zinc-300">{advice.strike_guidance}</div>
        </div>
        <div className="rounded-lg bg-zinc-950/60 p-3">
          <div className="text-xs font-medium text-zinc-500 mb-1">Expiry</div>
          <div className="text-sm text-zinc-300">{advice.expiry_guidance}</div>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-amber-300 mb-1.5">
          Before you act on this
        </div>
        <ul className="space-y-1.5 text-xs text-amber-200/90">
          {advice.critical_warnings?.map((w, i) => (
            <li key={i}>• {w}</li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
