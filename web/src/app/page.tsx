import { BriefingCard } from "@/components/BriefingCard";
import { CopilotCard } from "@/components/CopilotCard";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ForwardLogCard } from "@/components/ForwardLogCard";
import { IVCard } from "@/components/IVCard";
import { MarketTab } from "@/components/MarketCards";
import { NewsResearchCard } from "@/components/NewsResearchCard";
import { OpenInterestCard } from "@/components/OpenInterestCard";
import { JournalTab } from "@/components/JournalTab";
import { ReplicationCard } from "@/components/ReplicationCard";
import { PatternTable } from "@/components/PatternTable";
import { IndicatorGrid } from "@/components/IndicatorGrid";
import { LivePatternsCard } from "@/components/LivePatternsCard";
import { PatternOptionsTable, PatternsTodayCard } from "@/components/PatternCards";
import { PlaybookCard } from "@/components/PlaybookCard";
import { TodayChart } from "@/components/TodayChart";
import { RecommendationCard } from "@/components/RecommendationCard";
import { RegimeBadge } from "@/components/RegimeBadge";
import { SessionStatus } from "@/components/SessionStatus";
import { LiveTicker } from "@/components/LiveTicker";
import { AutoRefresh } from "@/components/AutoRefresh";
import { PairPhone } from "@/components/PairPhone";
import { PairingNotice } from "@/components/PairingNotice";
import { SimilarityCard } from "@/components/SimilarityCard";
import { ResearchCompare } from "@/components/ResearchCompare";
import { SectionLabel } from "@/components/ui";
import {
  fetchBriefing,
  fetchChart,
  fetchCopilotStatus,
  fetchForwardLog,
  fetchImpliedVol,
  fetchMarket,
  fetchStructural,
  fetchIndices,
  fetchReplication,
  fetchZerodhaStatus,
  fetchPaper,
  fetchIndicators,
  fetchLivePatterns,
  fetchLiveQuote,
  fetchNews,
  fetchNewsResearch,
  fetchOptionsChain,
  fetchPatternOptions,
  fetchPatternsToday,
  fetchPlaybook,
  fetchRecommendation,
  fetchResearchCompare,
  fetchSimilarity,
  fetchSnapshot,
  fetchStrategyFit,
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
    indices,
    replication,
    zerodha,
    paper,
    news,
    optionChain,
    newsResearch,
    strategyFit,
  ] = await Promise.all([
    fetchSnapshot(),
    fetchLiveQuote(),
    fetchRecommendation(),
    fetchIndicators(),
    fetchChart(),
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
    fetchIndices(),
    fetchReplication(),
    fetchZerodhaStatus(),
    fetchPaper(),
    fetchNews(),
    fetchOptionsChain(),
    fetchNewsResearch(),
    fetchStrategyFit(),
  ]);

  const snap = snapshot.data;
  const live = liveQuote.data;
  // Live NSE feed when reachable, daily close as the fallback — never a
  // fabricated number, and the header says which one is showing.
  const price = live?.last ?? snap?.price ?? null;
  // Missing is shown as missing ("–"), never as a +0.00 the code did not compute.
  const change = live?.change ?? snap?.change ?? null;
  const changePct = live?.change_pct ?? snap?.change_pct ?? null;

  return (
    <div className="min-h-full bg-zinc-950">
      <AutoRefresh />
      <PairingNotice />
      <header className="sticky top-0 z-10 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-8">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
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
              <div className="grid gap-6 lg:grid-cols-12">
                <section className="min-w-0 lg:col-span-7">
                  <SectionLabel hint="the only thing on this page that is a decision">Today&apos;s call</SectionLabel>
                  <RecommendationCard rec={recommendation.data} />
                  <div className="mt-6">
                    <IndicatorGrid initial={indicators.data} />
                  </div>
                </section>
                <section className="min-w-0 lg:col-span-5">
                  <SectionLabel hint="and the closes that would form a pattern">Where NIFTY stands</SectionLabel>
                  <TodayChart data={candles.data} />
                </section>
              </div>

              {livePatterns.data?.candle && (
                <section>
                  <SectionLabel hint="provisional until 15:30 — never a signal">Live — during the session</SectionLabel>
                  <LivePatternsCard initial={livePatterns.data} />
                </section>
              )}

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

              <section>
                <SectionLabel hint="from NSE's live chain — measurements, not validated signals">
                  Open interest
                </SectionLabel>
                <OpenInterestCard initial={optionChain.data} />
              </section>

              <section>
                <SectionLabel hint="explains the numbers above; never makes its own">Copilot</SectionLabel>
                <CopilotCard status={copilotStatus.data} />
              </section>

              <div className="grid gap-6 lg:grid-cols-2">
                <section className="min-w-0">
                  <SectionLabel hint="recorded before the outcome existed — never edited">
                    Forward track record
                  </SectionLabel>
                  <ForwardLogCard log={forwardLog.data} />
                </section>
                <section className="min-w-0">
                  <SectionLabel hint="what options cost, from NSE closing prices">
                    Implied volatility
                  </SectionLabel>
                  <IVCard data={impliedVol.data} />
                </section>
              </div>

              <section>
                <SectionLabel hint={briefing.data?.as_of?.slice(0, 10)}>Research briefing</SectionLabel>
                <BriefingCard briefing={briefing.data} />
              </section>
            </>
          }
          research={
            // Prototype of docs/DESIGN_DIRECTION.md, scoped to this tab so it
            // can be compared with the others before anything is rolled out.
            <div data-skin="instrument" className="flex flex-col gap-5">
              <section>
                <SectionLabel hint="2024–26, data the choice never saw">
                  What each pattern&apos;s option actually made
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

              {newsResearch.data && (
                <section>
                  <SectionLabel hint="tone of coverage, tested the same way as everything else">
                    Does the news pay a buyer?
                  </SectionLabel>
                  <NewsResearchCard data={newsResearch.data} />
                </section>
              )}

              {replication.data && (
                <section>
                  <SectionLabel hint="a date traded on several indices counts once">
                    The same rules on four indices
                  </SectionLabel>
                  <ReplicationCard data={replication.data} />
                </section>
              )}

              <section>
                <SectionLabel hint="past markets that looked like this one, and what followed">
                  Days like this one
                </SectionLabel>
                <SimilarityCard data={similarity.data} />
              </section>

              <details className="group rounded-xl border border-zinc-800/80 bg-zinc-900/40">
                <summary className="cursor-pointer list-none px-4 py-3 text-sm text-zinc-300 hover:text-zinc-100">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
                    Older work ▾
                  </span>
                  <span className="ml-2 text-[11px] text-zinc-600">
                    index-return verdicts, superseded by the option record above
                  </span>
                </summary>
                <div className="flex flex-col gap-6 border-t border-zinc-800/60 p-4">
                  <section>
                    <SectionLabel hint="index-return verdicts, stored as history">Strategy playbook</SectionLabel>
                    <PlaybookCard entries={playbook.data?.strategies ?? null} />
                  </section>
                  <section>
                    <SectionLabel hint="same costs, same hold, every strategy">Against buy-and-hold</SectionLabel>
                    <ResearchCompare result={compare.data} />
                  </section>
                </div>
              </details>
            </div>
          }
          market={<MarketTab data={market.data} structural={structural.data} indices={indices.data} news={news.data} fit={strategyFit.data} />}
          journal={<JournalTab paper={paper.data} />}
        />

        <div className="mt-10 flex flex-wrap items-center gap-3">
          <PairPhone />
        </div>

        <footer className="mt-6 border-t border-zinc-900 pt-4 text-[11px] leading-relaxed text-zinc-600">
          Every figure here is computed from real market data — nothing is estimated or filled in.
          Where a number isn&apos;t available, the section says so rather than showing a placeholder.
          No automatic trading, ever: this is decision support, and the trade decision stays yours.
        </footer>
      </main>
    </div>
  );
}
