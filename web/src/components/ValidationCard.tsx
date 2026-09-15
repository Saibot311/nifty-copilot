import type { ValidationResult } from "@/lib/api";

const STATUS_STYLE: Record<string, { ring: string; bg: string; text: string }> = {
  APPROVED: { ring: "ring-emerald-500/40", bg: "bg-emerald-500/10", text: "text-emerald-400" },
  CONDITIONAL: { ring: "ring-amber-500/40", bg: "bg-amber-500/10", text: "text-amber-400" },
  REJECTED: { ring: "ring-rose-500/40", bg: "bg-rose-500/10", text: "text-rose-400" },
};

export function ValidationCard({ result, live }: { result: ValidationResult | null; live: boolean }) {
  if (!live || !result) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 text-sm text-zinc-500">
        Validation results unavailable — the backend API isn&apos;t reachable right now.
      </div>
    );
  }

  const style = STATUS_STYLE[result.final_status] ?? STATUS_STYLE.CONDITIONAL;
  const wf = result.walk_forward;
  const ho = result.holdout;

  return (
    <div className={`rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 ring-1 ${style.ring}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
          Phase 8 — Walk-Forward Validation: EMA Pullback
        </div>
        <span className={`rounded-full px-3 py-1 text-sm font-bold ${style.bg} ${style.text}`}>
          {result.final_status}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-zinc-300">{result.final_reason}</p>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-medium text-zinc-500">
            Walk-forward folds ({wf.folds_with_positive_expectancy}/{wf.folds_with_any_trades} positive)
          </div>
          <div className="flex flex-col gap-1.5">
            {wf.folds.map((f, i) => {
              const exp = f.metrics.expectancy_pct;
              const positive = (exp ?? 0) > 0;
              const noTrades = f.metrics.num_trades === 0;
              return (
                <div key={i} className="flex items-center justify-between rounded-lg bg-zinc-950/60 px-3 py-1.5 text-xs">
                  <span className="text-zinc-500 font-mono">{f.period.start} → {f.period.end}</span>
                  <span className="flex items-center gap-2">
                    <span className="text-zinc-500">{f.metrics.num_trades}t</span>
                    <span className={`font-mono font-medium ${noTrades ? "text-zinc-600" : positive ? "text-emerald-400" : "text-rose-400"}`}>
                      {exp != null ? `${exp > 0 ? "+" : ""}${exp.toFixed(2)}%` : "n/a"}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <div className="mb-2 text-xs font-medium text-zinc-500">
            Development vs. holdout split (cut: {ho.split_date})
          </div>
          <div className="flex flex-col gap-2">
            <SplitRow label={`Development (${ho.development.period.start} → ${ho.development.period.end})`} metrics={ho.development.metrics} />
            <SplitRow label={`Holdout (${ho.holdout.period.start} → ${ho.holdout.period.end})`} metrics={ho.holdout.metrics} emphasize />
          </div>
        </div>
      </div>

      <details className="mt-4">
        <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-400">
          Methodology note — what this test can and can&apos;t prove
        </summary>
        <p className="mt-2 text-xs leading-relaxed text-zinc-500">{result.methodology_note}</p>
      </details>
    </div>
  );
}

function SplitRow({
  label,
  metrics,
  emphasize,
}: {
  label: string;
  metrics: { num_trades: number; expectancy_pct?: number };
  emphasize?: boolean;
}) {
  const exp = metrics.expectancy_pct;
  const positive = (exp ?? 0) > 0;
  return (
    <div className={`rounded-lg px-3 py-2 text-xs ${emphasize ? "bg-zinc-950/80 ring-1 ring-zinc-700" : "bg-zinc-950/60"}`}>
      <div className="text-zinc-500 font-mono mb-0.5">{label}</div>
      <div className="flex items-center gap-2">
        <span className="text-zinc-500">{metrics.num_trades} trades</span>
        <span className={`font-mono font-medium ${positive ? "text-emerald-400" : "text-rose-400"}`}>
          {exp != null ? `${exp > 0 ? "+" : ""}${exp.toFixed(2)}% expectancy` : "n/a"}
        </span>
      </div>
    </div>
  );
}
