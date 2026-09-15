import type { Recommendation } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

const ACTION_META: Record<
  string,
  { label: string; tone: "good" | "bad" | "warn"; accent: string; border: string }
> = {
  CONSIDER_CALL: {
    label: "CALL",
    tone: "good",
    accent: "text-emerald-400",
    border: "border-emerald-500/30 bg-emerald-500/[0.04]",
  },
  CONSIDER_PUT: {
    label: "PUT",
    tone: "bad",
    accent: "text-rose-400",
    border: "border-rose-500/30 bg-rose-500/[0.04]",
  },
  NO_TRADE: {
    label: "NO TRADE",
    tone: "warn",
    accent: "text-amber-400",
    border: "border-amber-500/25 bg-amber-500/[0.03]",
  },
};

export function RecommendationCard({ rec }: { rec: Recommendation | null }) {
  if (!rec) return <Offline what="Recommendation" />;

  const meta = ACTION_META[rec.action] ?? ACTION_META.NO_TRADE;

  return (
    <Panel emphasis="raised" className={`${meta.border} overflow-hidden`}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800/70 px-5 py-4">
        <div className="min-w-0">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
            Today&apos;s call
          </div>
          <p className={`text-xl font-semibold tracking-tight ${meta.accent}`}>{rec.headline}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Pill tone="neutral">{rec.regime.replace("_", " ")}</Pill>
          <span
            className={`rounded-lg border px-3 py-1.5 font-mono text-sm font-bold ${meta.border} ${meta.accent}`}
          >
            {meta.label}
          </span>
        </div>
      </div>

      <p className="px-5 py-4 text-sm leading-relaxed text-zinc-300">{rec.reason}</p>

      {rec.candidates.length > 0 && (
        <div className="border-t border-zinc-800/70 px-5 py-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-zinc-500">
            Signals firing today
          </div>
          <div className="flex flex-col gap-1.5">
            {rec.candidates.map((c) => (
              <div
                key={c.strategy}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-zinc-950/60 px-3 py-2"
              >
                <span className="flex items-center gap-2 text-xs text-zinc-300">
                  <span
                    className={`font-mono text-[10px] font-bold ${
                      c.option_type === "CE" ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {c.option_type}
                  </span>
                  {c.label}
                </span>
                <span className="flex items-center gap-3 text-[11px]">
                  <span
                    className={`font-mono tabular-nums ${
                      (c.index_expectancy_pct ?? 0) > 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {c.index_expectancy_pct != null
                      ? `${c.index_expectancy_pct > 0 ? "+" : ""}${c.index_expectancy_pct}%`
                      : "–"}
                  </span>
                  <span className="text-zinc-600">{c.index_trades} trades</span>
                  {c.qualifies ? (
                    <Pill tone="good">clears bar</Pill>
                  ) : (
                    <span className="text-zinc-600">{c.why_not}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {rec.warnings.length > 0 && (
        <div className="border-t border-zinc-800/70 bg-zinc-950/40 px-5 py-4">
          <ul className="space-y-1.5">
            {rec.warnings.map((w, i) => (
              <li key={i} className="flex gap-2 text-[11px] leading-relaxed text-amber-200/70">
                <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-amber-500/50" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
