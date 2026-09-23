import { BriefingCard } from "@/components/BriefingCard";
import { CopilotCard } from "@/components/CopilotCard";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ForwardLogCard } from "@/components/ForwardLogCard";
import { IVCard } from "@/components/IVCard";
import { MarketTab } from "@/components/MarketCards";
import { JournalTab } from "@/components/JournalTab";
import { ReplicationCard } from "@/components/ReplicationCard";
import { PatternTable } from "@/components/PatternTable";
import { IndicatorGrid } from "@/components/IndicatorGrid";
import { LivePatternsCard } from "@/components/LivePatternsCard";
import { PatternOptionsTable, PatternsTodayCard } from "@/components/PatternCards";
import { PlaybookCard } from "@/components/PlaybookCard";
import { PriceChart } from "@/components/PriceChart";
import { RecommendationCard } from "@/components/RecommendationCard";
import { RegimeBadge } from "@/components/RegimeBadge";
import { SessionStatus } from "@/components/SessionStatus";
import { LiveTicker } from "@/components/LiveTicker";
import { AutoRefresh } from "@/components/AutoRefresh";
import { SimilarityCard } from "@/components/SimilarityCard";
import { ResearchCompare } from "@/components/ResearchCompare";
import { SectionLabel } from "@/components/ui";
import {
  fetchBriefing,
  fetchCandles,
  fetchCopilotStatus,
  fetchForwardLog,
  fetchImpliedVol,
  fetchMarket,
  fetchStructural,
  fetchGiftNifty,
  fetchReplication,
  fetchZerodhaStatus,
  fetchPaper,
  fetchIndicators,
  fetchLivePatterns,
  fetchLiveQuote,
  fetchPatternOptions,
  fetchPatternsToday,
  fetchPlaybook,
  fetchRecommendation,
  fetchResearchCompare,
  fetchSimilarity,
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
    similarity,
    copilotStatus,
    impliedVol,
    market,
    structural,
    gift,
    replication,
    zerodha,
    paper,
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
    fetchSimilarity(),
    fetchCopilotStatus(),
    fetchImpliedVol(),
    fetchMarket(),
    fetchStructural(),
    fetchGiftNifty(),
    fetchReplication(),
    fetchZerodhaStatus(),
    fetchPaper(),
  ]);

  const snap = snapshot.data;
  const live = liveQuote.data;
  // Live NSE feed when reachable, daily close as the fallback — never a
  // fabricated number, and the header says which one is showing.
  const price = live?.last ?? snap?.price ?? null;
  const change = live?.change ?? snap?.change ?? 0;
  const changePct = live?.change_pct ?? snap?.change_pct ?? 0;

  return (
    <div className="min-h-full bg-zinc-950">
      <AutoRefresh />
      <header className="sticky top-0 z-10 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-8">
          <div className="flex items-baseline gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
              NIFTY 50
            </span>
            <LiveTicker fallback={{ price, change, changePct }} />
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
            <SessionStatus status={zerodha.data} />
            {snap && <RegimeBadge regime={snap.regime} />}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8">
        <DashboardTabs
          today={
            <>
              {livePatterns.data?.candle && (
                <section>
                  <SectionLabel hint="updates every 15-minute close">Live — during the session</SectionLabel>
                  <LivePatternsCard initial={livePatterns.data} />
                </section>
              )}

              <div className="grid gap-6 lg:grid-cols-12">
                <section className="lg:col-span-7">
                  <SectionLabel hint="the only thing on this page that is a decision">Today&apos;s call</SectionLabel>
                  <RecommendationCard rec={recommendation.data} />
                </section>
                <section className="lg:col-span-5">
                  <SectionLabel hint="with 20- and 50-day EMAs">Price</SectionLabel>
                  <PriceChart candles={candles.data?.candles ?? null} />
                  <div className="mt-3">
                    <IndicatorGrid indicators={indicators.data} />
                  </div>
                </section>
              </div>

              <section>
                <SectionLabel hint="explains the numbers above; never makes its own">Copilot</SectionLabel>
                <CopilotCard status={copilotStatus.data} />
              </section>

              <section>
                <SectionLabel hint={patternsToday.data ? `from the close of ${patternsToday.data.as_of} (${patternsToday.data.last_close.toLocaleString("en-IN")})` : undefined}>
                  Patterns in play
                </SectionLabel>
                {patternsToday.data ? (
                  <PatternTable
                    today={patternsToday.data.patterns.filter((p) => p.formed_today || (p.probability_next ?? 0) >= 0.02)}
                    caption="All 26, tested, are in Research."
                  />
                ) : (
                  <PatternsTodayCard data={patternsToday.data} />
                )}
              </section>

              <div className="grid gap-6 lg:grid-cols-2">
                <section>
                  <SectionLabel hint="recorded before the outcome existed — never edited">
                    Forward track record
                  </SectionLabel>
                  <ForwardLogCard log={forwardLog.data} />
                </section>
                <section>
                  <SectionLabel hint="what options cost, from NSE closing prices">
                    Implied volatility
                  </SectionLabel>
                  <IVCard data={impliedVol.data} />
                </section>
                <section>
                  <SectionLabel hint={briefing.data?.as_of?.slice(0, 10)}>Research briefing</SectionLabel>
                  <BriefingCard briefing={briefing.data} />
                </section>
                <section>
                  <SectionLabel hint="past markets that looked like this one, and what followed">
                    Similar past days
                  </SectionLabel>
                  <SimilarityCard data={similarity.data} />
                </section>
              </div>
            </>
          }
          research={
            <>
              <section>
                <SectionLabel hint="ranked by real option profit on data the choice never saw">
                  Every pattern, and the option it points to
                </SectionLabel>
                {patternOptions.data ? (
                  <PatternTable
                    research={patternOptions.data.patterns}
                    caption={`${patternOptions.data.configs_tested_total.toLocaleString("en-IN")} option setups tested · chosen on ${patternOptions.data.options_period.start}–${patternOptions.data.options_period.split}, judged on ${patternOptions.data.options_period.split}–${patternOptions.data.options_period.end}`}
                  />
                ) : (
                  <PatternOptionsTable data={patternOptions.data} />
                )}
              </section>

              {replication.data && (
                <section>
                  <SectionLabel hint="same rules, more trades — BANKNIFTY, Sensex, Midcap">Replicated on other indices</SectionLabel>
                  <ReplicationCard data={replication.data} />
                </section>
              )}

              <div className="grid gap-6 lg:grid-cols-2">
                <section>
                  <SectionLabel hint="index-return verdicts, stored as history">Strategy Playbook</SectionLabel>
                  <PlaybookCard entries={playbook.data?.strategies ?? null} />
                </section>
                <section>
                  <SectionLabel>Strategy comparison</SectionLabel>
                  <ResearchCompare result={compare.data} />
                </section>
              </div>
            </>
          }
          market={<MarketTab data={market.data} structural={structural.data} gift={gift.data} />}
          journal={<JournalTab paper={paper.data} />}
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
