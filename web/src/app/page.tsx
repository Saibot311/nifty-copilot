import { BriefingCard } from "@/components/BriefingCard";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ForwardLogCard } from "@/components/ForwardLogCard";
import { IndicatorGrid } from "@/components/IndicatorGrid";
import { LivePatternsCard } from "@/components/LivePatternsCard";
import { PatternOptionsTable, PatternsTodayCard } from "@/components/PatternCards";
import { PlaybookCard } from "@/components/PlaybookCard";
import { PriceChart } from "@/components/PriceChart";
import { RecommendationCard } from "@/components/RecommendationCard";
import { RegimeBadge } from "@/components/RegimeBadge";
import { ResearchCompare } from "@/components/ResearchCompare";
import { SectionLabel } from "@/components/ui";
import {
  fetchBriefing,
  fetchCandles,
  fetchForwardLog,
  fetchIndicators,
  fetchLivePatterns,
  fetchLiveQuote,
  fetchPatternOptions,
  fetchPatternsToday,
  fetchPlaybook,
  fetchRecommendation,
  fetchResearchCompare,
  fetchSnapshot,
} from "@/lib/api";

export default async function Home() {
  const [
    snapshot,
    liveQuote,
    recommendation,
    indicators,
    candles,
    briefing,
    compare,
    playbook,
    forwardLog,
    patternsToday,
    patternOptions,
    livePatterns,
  ] = await Promise.all([
    fetchSnapshot(),
    fetchLiveQuote(),
    fetchRecommendation(),
    fetchIndicators(),
    fetchCandles(),
    fetchBriefing(),
    fetchResearchCompare(),
    fetchPlaybook(),
    fetchForwardLog(),
    fetchPatternsToday(),
    fetchPatternOptions(),
    fetchLivePatterns(),
  ]);

  const snap = snapshot.data;
  const live = liveQuote.data;
  // Live NSE feed when reachable, daily close as the fallback — never a
  // fabricated number, and the header says which one is showing.
  const price = live?.last ?? snap?.price ?? null;
  const change = live?.change ?? snap?.change ?? 0;
  const changePct = live?.change_pct ?? snap?.change_pct ?? 0;
  const isUp = change >= 0;

  return (
    <div className="min-h-full bg-zinc-950">
      <header className="sticky top-0 z-10 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-8">
          <div className="flex items-baseline gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
              NIFTY 50
            </span>
            {price != null ? (
              <>
                <span className="font-mono text-2xl font-semibold tracking-tight text-zinc-50 tabular-nums">
                  {price.toLocaleString("en-IN")}
                </span>
                <span
                  className={`font-mono text-sm font-medium tabular-nums ${
                    isUp ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {isUp ? "+" : ""}
                  {change.toFixed(2)} ({isUp ? "+" : ""}
                  {changePct.toFixed(2)}%)
                </span>
                {live && (
                  <span
                    className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${
                      live.market.is_open ? "text-emerald-400" : "text-zinc-500"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        live.market.is_open ? "animate-pulse bg-emerald-400" : "bg-zinc-600"
                      }`}
                    />
                    {live.market.is_open ? "Live" : "Closed"}
                  </span>
                )}
              </>
            ) : (
              <span className="text-sm text-zinc-500">backend offline</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {live?.india_vix != null && (
              <span className="font-mono text-[11px] text-zinc-500 tabular-nums">
                VIX {live.india_vix}
              </span>
            )}
            <span className="text-[11px] text-zinc-600">
              {live ? live.market.trade_date : snap?.as_of}
            </span>
            {snap && <RegimeBadge regime={snap.regime} />}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8">
        <DashboardTabs
          today={
            <>
              {livePatterns.data?.candle && (
                <section>
                  <SectionLabel hint="updates every 15-minute close">Live — during the session</SectionLabel>
                  <LivePatternsCard initial={livePatterns.data} />
                </section>
              )}

              <section>
                <SectionLabel>Recommendation</SectionLabel>
                <RecommendationCard rec={recommendation.data} />
              </section>

              <section>
                <SectionLabel hint="each with the option it points to and what that option made">
                  Patterns
                </SectionLabel>
                <PatternsTodayCard data={patternsToday.data} />
              </section>

              <section>
                <SectionLabel hint="recorded before the outcome existed — never edited">
                  Forward track record
                </SectionLabel>
                <ForwardLogCard log={forwardLog.data} />
              </section>

              <section>
                <SectionLabel hint={briefing.data?.as_of?.slice(0, 10)}>
                  Research briefing
                </SectionLabel>
                <BriefingCard briefing={briefing.data} />
              </section>

              <section>
                <SectionLabel hint="with 20- and 50-day EMAs">
                  Price
                </SectionLabel>
                <PriceChart candles={candles.data?.candles ?? null} />
              </section>

              <section>
                <SectionLabel>Indicators</SectionLabel>
                <IndicatorGrid indicators={indicators.data} />
              </section>
            </>
          }
          research={
            <>
              <section>
                <SectionLabel hint="ranked by real option profit on unseen data">
                  Pattern → option
                </SectionLabel>
                <PatternOptionsTable data={patternOptions.data} />
              </section>

              <section>
                <SectionLabel hint="index-return verdicts, stored as history">Strategy Playbook</SectionLabel>
                <PlaybookCard entries={playbook.data?.strategies ?? null} />
              </section>

              <section>
                <SectionLabel>Strategy comparison</SectionLabel>
                <ResearchCompare result={compare.data} />
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
