import { ChartPlaceholder } from "@/components/ChartPlaceholder";
import { IndicatorGrid } from "@/components/IndicatorGrid";
import { RegimeBadge } from "@/components/RegimeBadge";
import { ScenarioCard } from "@/components/ScenarioCard";
import { mockIndicators, mockScenarios, mockSnapshot } from "@/lib/mock-data";

export default function Home() {
  const isUp = mockSnapshot.change >= 0;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-4 py-8 sm:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm text-zinc-500">{mockSnapshot.symbol}</div>
          <div className="flex items-baseline gap-3">
            <span className="text-4xl font-semibold tracking-tight text-zinc-50">
              {mockSnapshot.price.toLocaleString("en-IN")}
            </span>
            <span className={`text-base font-medium ${isUp ? "text-emerald-400" : "text-rose-400"}`}>
              {isUp ? "+" : ""}
              {mockSnapshot.change.toFixed(2)} ({isUp ? "+" : ""}
              {mockSnapshot.changePct.toFixed(2)}%)
            </span>
          </div>
          <div className="mt-1 text-xs text-zinc-600">
            {mockSnapshot.asOf}
            {mockSnapshot.provisional && " · provisional — candle still forming"}
          </div>
        </div>
        <RegimeBadge regime={mockSnapshot.regime} />
      </header>

      <section aria-labelledby="chart-heading">
        <h2 id="chart-heading" className="mb-3 text-sm font-medium text-zinc-400">
          Price
        </h2>
        <ChartPlaceholder />
      </section>

      <section aria-labelledby="indicators-heading">
        <h2 id="indicators-heading" className="mb-3 text-sm font-medium text-zinc-400">
          Indicators
        </h2>
        <IndicatorGrid indicators={mockIndicators} />
      </section>

      <section aria-labelledby="scenarios-heading">
        <h2 id="scenarios-heading" className="mb-3 text-sm font-medium text-zinc-400">
          Scenarios
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          {mockScenarios.map((s) => (
            <ScenarioCard key={s.kind} scenario={s} />
          ))}
        </div>
      </section>

      <footer className="mt-4 border-t border-zinc-900 pt-4 text-xs text-zinc-600">
        All figures on this page are placeholder mock data (Phase 2 — UI shell only). No live market
        data, no real backtests, and no automatic trading — you always make the final decision.
      </footer>
    </div>
  );
}
