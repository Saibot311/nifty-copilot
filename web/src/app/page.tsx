import { BriefingCard } from "@/components/BriefingCard";
import { CopilotCard } from "@/components/CopilotCard";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ForwardLogCard } from "@/components/ForwardLogCard";
import { IVCard } from "@/components/IVCard";
import { MarketTab } from "@/components/MarketCards";
import { NewsResearchCard } from "@/components/NewsResearchCard";
import { OptionChainCard } from "@/components/OptionChainCard";
import { JournalTab } from "@/components/JournalTab";
import { ReplicationCard } from "@/components/ReplicationCard";
import { CourseResearchCard } from "@/components/CourseResearchCard";
import { IntradayCard } from "@/components/IntradayCard";
import { BreakoutLevelsCard } from "@/components/BreakoutLevelsCard";
import { WeekdayCard } from "@/components/WeekdayCard";
import { OptionMovesCard } from "@/components/OptionMovesCard";
import { DayForecastCard } from "@/components/DayForecastCard";
import { NiftyPipelineCard } from "@/components/NiftyPipelineCard";
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
import { FreshnessStrip } from "@/components/FreshnessStrip";
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
  fetchCourseResearch,
  fetchIntraday,
  fetchWeekdayProfile,
  fetchOptionMoves,
  fetchDayForecast,
  fetchBreakouts,
  fetchFreshness,
  fetchNiftyPipeline,
  fetchZerodhaStatus,
  fetchPaper,
  fetchIndicators,
  fetchLivePatterns,
  fetchLiveQuote,
  fetchNews,
  fetchNewsResearch,
  fetchOptionChainTable,
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
    chainTable,
    newsResearch,
    strategyFit,
    courseResearch,
    niftyPipeline,
    intraday,
    weekdayProfile,
    optionMoves,
    dayForecast,
    breakouts,
    freshness,
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
    fetchOptionChainTable(),
    fetchNewsResearch(),
    fetchStrategyFit(),
    fetchCourseResearch(),
    fetchNiftyPipeline(),
    fetchIntraday(),
    fetchWeekdayProfile(),
    fetchOptionMoves(),
    fetchDayForecast(),
    fetchBreakouts(),
    fetchFreshness(),
  ]);

  const snap = snapshot.data;
  const live = liveQuote.data;
  // Live NSE feed when reachable, daily close as the fallback — never a
  // fabricated number, and the header says which one is showing.
  const price = live?.last ?? snap?.price ?? null;
  // Missing is shown as missing ("–"), never as a +0.00 the code did not compute.
  const change = live?.change ?? snap?.change ?? null;
  const changePct = live?.change_pct ?? snap?.change_pct ?? null;

  // A card's reason for being behind, from the watchdog's freshness check.
  const behind = (...keys: string[]) =>
    freshness.data?.sources.find((x) => keys.includes(x.key) && x.status === "behind")?.reason ?? null;

  return (
    <div className="min-h-full bg-zinc-950">
      {/* Changes on every server render: AutoRefresh reloads a tab whose refreshes stop landing. */}
      <time id="page-rendered-at" dateTime={new Date().toISOString()} hidden />
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
        <FreshnessStrip data={freshness.data} />
        <DashboardTabs
          today={
            <>
              <div className="grid gap-6 lg:grid-cols-12">
                <section className="min-w-0 lg:col-span-7">
                  <SectionLabel hint="the only thing on this page that is a decision" behind={behind("recommendation")}>Today&apos;s call</SectionLabel>
                  <RecommendationCard rec={recommendation.data} />
                  <div className="mt-6">
                    <IndicatorGrid initial={indicators.data} />
                  </div>
                </section>
                <section className="min-w-0 lg:col-span-5">
                  <SectionLabel hint="4-hour candles, and the closes that would form a pattern that could become the call" behind={behind("chart")}>Where NIFTY stands</SectionLabel>
                  <TodayChart data={candles.data} />
                </section>
              </div>

              <section>
                <SectionLabel hint="written before the session, scored after — how far, not which way" behind={behind("day_forecast")}>
                  The next session
                </SectionLabel>
                <DayForecastCard data={dayForecast.data} />
              </section>

              {livePatterns.data?.candle && (
                <section>
                  <SectionLabel hint="provisional until 15:30 — never a signal" behind={behind("live_patterns", "indicators")}>Live — during the session</SectionLabel>
                  <LivePatternsCard initial={livePatterns.data} />
                </section>
              )}

              <section>
                <SectionLabel hint="the strategy pipeline's three, followed on completed 5-minute bars" behind={behind("intraday")}>
                  Intraday rules
                </SectionLabel>
                <IntradayCard initial={intraday.data} />
              </section>

              <section>
                <SectionLabel hint="from data that existed before each was used — every break since 2015 beside random levels" behind={behind("breakouts", "breakout_record")}>
                  Breakout levels
                </SectionLabel>
                <BreakoutLevelsCard data={breakouts.data} />
              </section>

              <section>
                <SectionLabel hint="every session of this weekday since 2015, point by point — a description, not a signal" behind={behind("weekday_profile")}>
                  How {weekdayProfile.data ? `${weekdayProfile.data.weekday}s` : "this weekday"} move
                </SectionLabel>
                <WeekdayCard data={weekdayProfile.data} />
              </section>

              <section>
                <SectionLabel hint="8 strikes either side of the money — modelled from each price now, and as traded" behind={behind("option_moves")}>
                  What a move does to option prices
                </SectionLabel>
                <OptionMovesCard data={optionMoves.data} />
              </section>

              <section>
                <SectionLabel hint={patternsToday.data ? `from the close of ${patternsToday.data.as_of} (${patternsToday.data.last_close.toLocaleString("en-IN")})` : undefined} behind={behind("patterns_today")}>
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
                <SectionLabel hint="NSE's live chain: every strike and expiry, open interest included — pick a price for what a lot costs" behind={behind("option_chain")}>
                  Option chain
                </SectionLabel>
                <OptionChainCard initial={chainTable.data} />
              </section>

              <section>
                <SectionLabel hint="explains the numbers above; never makes its own">Copilot</SectionLabel>
                <CopilotCard status={copilotStatus.data} />
              </section>

              <div className="grid gap-6 lg:grid-cols-2">
                <section className="min-w-0">
                  <SectionLabel hint="recorded before the outcome existed — never edited" behind={behind("forward_log")}>
                    Forward track record
                  </SectionLabel>
                  <ForwardLogCard log={forwardLog.data} />
                </section>
                <section className="min-w-0">
                  <SectionLabel hint="what options cost, from NSE closing prices" behind={behind("iv")}>
                    Implied volatility
                  </SectionLabel>
                  <IVCard data={impliedVol.data} />
                </section>
              </div>

              <section>
                <SectionLabel hint={briefing.data?.as_of?.slice(0, 10)} behind={behind("briefing")}>Research briefing</SectionLabel>
                <BriefingCard briefing={briefing.data} />
              </section>
            </>
          }
          research={
            // Prototype of docs/DESIGN_DIRECTION.md, scoped to this tab so it
            // can be compared with the others before anything is rolled out.
            <div data-skin="instrument" className="flex flex-col gap-5">
              {niftyPipeline.data && (
                <section>
                  <SectionLabel hint="fixed before they were run, judged once on 2024–26">
                    Strategies searched for NIFTY
                  </SectionLabel>
                  <NiftyPipelineCard data={niftyPipeline.data} />
                </section>
              )}

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
                  <SectionLabel hint="tone of coverage, tested the same way as everything else" behind={behind("news_research")}>
                    Does the news pay a buyer?
                  </SectionLabel>
                  <NewsResearchCard data={newsResearch.data} />
                </section>
              )}

              {courseResearch.data && (
                <section>
                  <SectionLabel hint="your own strategies, tested the same way as everything else">
                    Your course strategies
                  </SectionLabel>
                  <CourseResearchCard data={courseResearch.data} />
                </section>
              )}

              {replication.data && (
                <section>
                  <SectionLabel hint="a date traded on several indices counts once" behind={behind("replication")}>
                    The same rules on four indices
                  </SectionLabel>
                  <ReplicationCard data={replication.data} />
                </section>
              )}

              <section>
                <SectionLabel hint="past markets that looked like this one, and what followed" behind={behind("similarity")}>
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
