import type { OptionsAdvice } from "@/lib/api";

export function OptionsAdvisorCard({ advice, live }: { advice: OptionsAdvice | null; live: boolean }) {
  if (!live || !advice) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 text-sm text-zinc-500">
        Options advisor unavailable — the backend API isn&apos;t reachable right now.
      </div>
    );
  }

  if (!advice.actionable_today) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-2">
          EMA Pullback → Options Idea
        </div>
        <div className="rounded-lg bg-zinc-950/60 p-3 text-sm text-zinc-400">
          {advice.message}
        </div>
        {advice.recent_signal_dates.length > 0 && (
          <div className="mt-3 text-xs text-zinc-600">
            Last fired: {advice.recent_signal_dates[advice.recent_signal_dates.length - 1]}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 ring-1 ring-emerald-500/20">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-400">
          EMA Pullback → Options Idea (as of {advice.as_of})
        </div>
        <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-sm font-bold text-emerald-300">
          {advice.direction}
        </span>
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
    </div>
  );
}
