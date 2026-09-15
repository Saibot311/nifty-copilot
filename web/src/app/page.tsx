import { BacktestCard } from "@/components/BacktestCard";
import { BriefingCard } from "@/components/BriefingCard";
import { DashboardTabs } from "@/components/DashboardTabs";
import { IndicatorGrid } from "@/components/IndicatorGrid";
import { OptionsAdvisorCard } from "@/components/OptionsAdvisorCard";
import { OptionsStrikeSweep } from "@/components/OptionsStrikeSweep";
import { ParamSweepHeatmap } from "@/components/ParamSweepHeatmap";
import { PriceChart } from "@/components/PriceChart";
import { RegimeBadge } from "@/components/RegimeBadge";
import { ResearchCompare } from "@/components/ResearchCompare";
import { ValidationCard } from "@/components/ValidationCard";
import { SectionLabel } from "@/components/ui";
import {
  fetchBacktest,
  fetchBriefing,
  fetchCandles,
  fetchIndicators,
  fetchOptionsAdvisor,
  fetchOptionsArchive,
  fetchParamSweep,
  fetchResearchCompare,
  fetchSnapshot,
  fetchStrikeSweep,
  fetchValidation,
} from "@/lib/api";

export default async function Home() {
  const [
    snapshot,
    indicators,
    candles,
    briefing,
    optionsAdvice,
    backtest,
    compare,
    paramSweep,
    validation,
    strikeSweep,
    archive,
  ] = await Promise.all([
    fetchSnapshot(),
    fetchIndicators(),
    fetchCandles(),
    fetchBriefing(),
    fetchOptionsAdvisor(),
    fetchBacktest(),
    fetchResearchCompare(),
    fetchParamSweep(),
    fetchValidation(),
    fetchStrikeSweep(),
    fetchOptionsArchive(),
  ]);

  const snap = snapshot.data;
  const isUp = (snap?.change ?? 0) >= 0;

  return (
    <div className="min-h-full bg-zinc-950">
      <header className="sticky top-0 z-10 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-8">
          <div className="flex items-baseline gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
              NIFTY 50
            </span>
            {snap ? (
              <>
                <span className="font-mono text-2xl font-semibold tracking-tight text-zinc-50 tabular-nums">
                  {snap.price.toLocaleString("en-IN")}
                </span>
                <span
                  className={`font-mono text-sm font-medium tabular-nums ${
                    isUp ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {isUp ? "+" : ""}
                  {snap.change.toFixed(2)} ({isUp ? "+" : ""}
                  {snap.change_pct.toFixed(2)}%)
                </span>
              </>
            ) : (
              <span className="text-sm text-zinc-500">backend offline</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {snap && <span className="text-[11px] text-zinc-600">{snap.as_of}</span>}
            {snap && <RegimeBadge regime={snap.regime} />}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8">
        <DashboardTabs
          today={
            <>
              <section>
                <SectionLabel hint={briefing.data?.as_of?.slice(0, 10)}>
                  Research briefing
                </SectionLabel>
                <BriefingCard briefing={briefing.data} />
              </section>

              <section>
                <SectionLabel hint="EMA20 and EMA50 are the lines the strategy reads">
                  Price
                </SectionLabel>
                <PriceChart candles={candles.data?.candles ?? null} />
              </section>

              <section>
                <SectionLabel>Indicators</SectionLabel>
                <IndicatorGrid indicators={indicators.data} />
              </section>

              <section>
                <SectionLabel>Options helper</SectionLabel>
                <OptionsAdvisorCard advice={optionsAdvice.data} />
              </section>
            </>
          }
          research={
            <>
              <section>
                <SectionLabel hint="returns on premium, not index">
                  Which option to buy
                </SectionLabel>
                <OptionsStrikeSweep sweep={strikeSweep.data} archive={archive.data} />
              </section>

              <section>
                <SectionLabel hint="the verdict that matters">Walk-forward validation</SectionLabel>
                <ValidationCard result={validation.data} />
              </section>

              <section>
                <SectionLabel>Strategy comparison</SectionLabel>
                <ResearchCompare result={compare.data} />
              </section>

              <section>
                <SectionLabel hint="does the edge survive nearby settings?">
                  Parameter robustness
                </SectionLabel>
                <ParamSweepHeatmap result={paramSweep.data} />
              </section>

              <section>
                <SectionLabel>EMA Pullback backtest detail</SectionLabel>
                <BacktestCard result={backtest.data} />
              </section>
            </>
          }
        />

        <footer className="mt-10 border-t border-zinc-900 pt-4 text-[11px] leading-relaxed text-zinc-600">
          Every figure here is computed from real market data — nothing is estimated or filled in.
          Where a number isn&apos;t available, the section says so rather than showing a placeholder.
          No automatic trading, ever: this is decision support, and the trade decision stays yours.
        </footer>
      </main>
    </div>
  );
}
