import type { ValidationResult } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

const TONE: Record<string, "good" | "warn" | "bad"> = {
  APPROVED: "good",
  CONDITIONAL: "warn",
  REJECTED: "bad",
};

export function ValidationCard({ result }: { result: ValidationResult | null }) {
  if (!result) return <Offline what="Validation" />;

  const wf = result.walk_forward;
  const ho = result.holdout;

  return (
    <Panel emphasis="raised" className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
          Walk-forward validation · EMA Pullback
        </div>
        <Pill tone={TONE[result.final_status] ?? "warn"}>{result.final_status}</Pill>
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
    </Panel>
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
