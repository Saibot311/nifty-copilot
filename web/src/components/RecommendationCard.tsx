import type { Recommendation } from "@/lib/api";
import { Offline, Panel, Pill, minus } from "./ui";

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
            Formed on the last close
          </div>
          <div className="flex flex-col gap-1.5">
            {rec.candidates.map((c) => (
              <div key={c.strategy} className="rounded-lg bg-zinc-950/60 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
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
                  <Pill tone={c.qualifies ? "good" : c.status === "CONDITIONAL" ? "warn" : "bad"}>
                    {c.qualifies ? "clears bar" : c.status}
                  </Pill>
                </div>
                {c.suggested_option && (
                  <p className="mt-1 font-mono text-[11px] tabular-nums text-zinc-500">
                    {c.suggested_option} · 2024–26: {c.holdout_trades} trades,{" "}
                    {c.holdout_avg_profit_per_lot_rs != null
                      ? `${c.holdout_avg_profit_per_lot_rs >= 0 ? "+" : "−"}₹${Math.abs(c.holdout_avg_profit_per_lot_rs).toLocaleString("en-IN")}/lot`
                      : "–"}
                    , t {minus(c.holdout_t_stat)}
                  </p>
                )}
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

      {rec.evidence_bar && (
        <details className="border-t border-zinc-800/70 px-5 py-3">
          <summary className="cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-400">
            Evidence bar: option verdict APPROVED and t ≥ {rec.evidence_bar.min_t} (
            {rec.evidence_bar.tests_judged ?? rec.evidence_bar.patterns_judged} hypotheses judged on 2024–26)
          </summary>
          <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">
            {rec.evidence_bar.methodology_note}
          </p>
        </details>
      )}
    </Panel>
  );
}
