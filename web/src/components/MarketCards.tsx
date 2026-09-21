import type { MarketContext, MarketStudies, MarketToday, Principle } from "@/lib/api";
import { Offline, Panel, Pill, SectionLabel } from "./ui";

function signed(v: number | null | undefined, digits = 2, unit = "%") {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}${unit}`;
}

function pct(v: number | null | undefined) {
  return v == null ? "–" : `${Math.round(v * 100)}%`;
}

function contracts(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-IN")}`;
}

export function WhyItMovedCard({ today }: { today: MarketToday }) {
  const w = today.why_it_moved;
  if (!w.available) return <Offline what={`Why it moved (${w.reason})`} />;
  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[11px] text-zinc-500">NIFTY on {w.date}</div>
        <div className="font-mono text-2xl font-semibold tabular-nums text-zinc-50">{signed(w.nifty_return_pct)}</div>
      </div>
      <p className="mt-1 text-xs text-zinc-400">
        Opened {signed(w.gap_pct)} from the previous close, then moved {signed(w.intraday_pct)} during the session.
      </p>
      <table className="mt-3 w-full text-left text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-zinc-500">
          <tr><th className="py-1 font-medium">Before India opened</th><th className="py-1 text-right font-medium">moved</th><th className="py-1 text-right font-medium">accounts for</th></tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {Object.entries(w.factors ?? {}).map(([k, f]) => (
            <tr key={k} className="border-t border-zinc-800/70">
              <td className="py-1.5 font-sans text-zinc-300">{f.label}</td>
              <td className="py-1.5 text-right text-zinc-400">{signed(f.move_pct)}</td>
              <td className="py-1.5 text-right text-zinc-200">{signed(f.contribution_pct)}</td>
            </tr>
          ))}
          <tr className="border-t border-zinc-700">
            <td className="py-1.5 font-sans text-zinc-300">Global cues together</td><td />
            <td className="py-1.5 text-right text-zinc-100">{signed(w.explained_by_global_pct)}</td>
          </tr>
          <tr className="border-t border-zinc-800/70">
            <td className="py-1.5 font-sans text-zinc-300">Unexplained — domestic news, flows, positioning, noise</td><td />
            <td className="py-1.5 text-right text-zinc-100">{signed(w.unexplained_pct)}</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
        {w.note} Over the past year these three accounted for {pct(w.fit_r2_past_year)} of NIFTY&apos;s day-to-day movement.
      </p>
    </Panel>
  );
}

export function WhoWinsCard({ studies, today }: { studies: MarketStudies; today: MarketToday }) {
  const v = studies.variance_risk_premium;
  const b = studies.option_buyers_without_a_signal;
  const fy26 = studies.sebi.fy26;
  const fy24 = studies.sebi.fy24_winners;
  const pos = today.positioning;
  const hist = studies.positioning_history;
  const now = today.options_price_now;
  return (
    <Panel className="p-4">
      <div className="rounded-lg bg-zinc-800/60 px-3 py-2 text-xs leading-relaxed text-zinc-300">
        <span className="font-semibold text-zinc-100">SEBI, on client-level data: </span>
        {fy26.share_of_individuals_losing} of individual F&amp;O traders lost money in FY26 — {fy26.aggregate_net_loss} in
        total, {fy26.share_of_losses_from_options} of it on options. In FY24 proprietary desks made{" "}
        {fy24.proprietary_gross_profit} and foreign institutions {fy24.fpi_gross_profit}, {fy24.share_via_algorithms} through
        algorithms.
      </div>

      <h3 className="mt-4 text-sm font-medium text-zinc-100">Options are usually priced for more movement than arrives</h3>
      <p className="mt-1 text-xs leading-relaxed text-zinc-400">
        Measured on NIFTY over {v.days.toLocaleString("en-IN")} days ({v.period}): 30-day implied volatility averaged{" "}
        {v.avg_implied}%, the volatility that then arrived {v.avg_delivered}%. Options were priced above what followed on{" "}
        {pct(v.options_overpriced_share)} of days. That gap is what option sellers collect and buyers pay — until a crash:
        in {v.when_sellers_were_hurt[0]?.date.slice(0, 7)} options priced {v.when_sellers_were_hurt[0]?.implied}% and the
        market delivered {v.when_sellers_were_hurt[0]?.delivered}%.
      </p>
      {b.available && (
        <p className="mt-2 text-xs leading-relaxed text-zinc-400">
          Buying each pattern&apos;s option on a fixed schedule over 2024–26, with no signal, lost a median ₹
          {Math.abs(b.median_rupees_per_lot ?? 0).toLocaleString("en-IN")} per lot; {b.setups_that_made_money} of {b.setups} setups made money.
        </p>
      )}
      {now && (
        <p className="mt-2 text-xs leading-relaxed text-zinc-500">
          Now: options price {now.implied}% volatility; the index actually moved {now.delivered_last_21_sessions}% (annualised)
          over the last 21 sessions.
        </p>
      )}

      <h3 className="mt-4 text-sm font-medium text-zinc-100">Who holds what{pos.available && `, ${pos.date}`}</h3>
      {pos.available && pos.by_participant ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="py-1 font-medium">Participant</th>
                <th className="py-1 text-right font-medium">Index futures, net</th>
                <th className="py-1 text-right font-medium">vs previous day</th>
                <th className="py-1 text-right font-medium">Options held long</th>
                <th className="py-1 text-right font-medium">Usually (since 2019)</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {Object.entries(pos.by_participant).map(([p, x]) => (
                <tr key={p} className="border-t border-zinc-800/70">
                  <td className="py-1.5 font-sans text-zinc-300">{p === "Client" ? "Client (mostly retail)" : p === "Pro" ? "Pro (brokers' own money)" : p}</td>
                  <td className="py-1.5 text-right text-zinc-200">{contracts(x.index_futures_net)}</td>
                  <td className="py-1.5 text-right text-zinc-400">{contracts(x.index_futures_net_change)}</td>
                  <td className="py-1.5 text-right text-zinc-200">{pct(x.options_buyer_share)}</td>
                  <td className="py-1.5 text-right text-zinc-500">{pct(hist.by_participant?.[p]?.median_options_buyer_share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">
            {pos.note} &ldquo;Options held long&rdquo;: of a participant&apos;s index-option contracts, the share it bought rather
            than sold. {hist.period && `History: ${hist.days} sessions, ${hist.period}.`}
          </p>
        </div>
      ) : (
        <p className="mt-1 text-xs text-zinc-500">{pos.reason}</p>
      )}
    </Panel>
  );
}

function Footprint({ label, c }: { label: string; c: MarketStudies["expiry_footprints"]["all"] }) {
  const clear = (z: number | null) => z != null && Math.abs(z) >= 2;
  return (
    <tr className="border-t border-zinc-800/70">
      <td className="py-1.5 font-sans text-zinc-300">{label}</td>
      <td className="py-1.5 text-right">{pct(c.reversal.expiry_share)} vs {pct(c.reversal.other_share)} <span className={clear(c.reversal.z) ? "text-amber-300" : "text-zinc-600"}>z {c.reversal.z ?? "–"}</span></td>
      <td className="py-1.5 text-right">{c.settlement_window.expiry_avg_abs_move_pct}% vs {c.settlement_window.other_avg_abs_move_pct}% <span className={clear(c.settlement_window.t) ? "text-amber-300" : "text-zinc-600"}>t {c.settlement_window.t ?? "–"}</span></td>
      <td className="py-1.5 text-right">{pct(c.pinning.expiry_share_near_strike)} vs {pct(c.pinning.other_share_near_strike)} <span className={clear(c.pinning.z) ? "text-amber-300" : "text-zinc-600"}>z {c.pinning.z ?? "–"}</span></td>
    </tr>
  );
}

export function ExpiryCard({ studies, today }: { studies: MarketStudies; today: MarketToday }) {
  const e = today.expiry;
  const u = today.unusual_strike_activity;
  const f = studies.expiry_footprints;
  return (
    <Panel className="p-4">
      {e.available && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-300">
          <span>Next NIFTY expiry: <span className="font-mono text-zinc-100">{e.next_expiry ?? "–"}</span></span>
          <span className="text-zinc-600">·</span>
          <span>
            Latest session {e.date}{e.was_expiry ? " (an expiry day)" : ""}: morning {signed(e.morning_pct)}, afternoon{" "}
            {signed(e.afternoon_pct)}, last 30 minutes {signed(e.last30_pct)}
          </span>
          {e.sharp_reversal && <Pill tone="warn">sharp reversal</Pill>}
        </div>
      )}

      <h3 className="mt-4 text-sm font-medium text-zinc-100">Unusual activity at a strike</h3>
      {u.available ? (
        u.unusual && u.unusual.length ? (
          <ul className="mt-1 flex flex-col gap-1 text-xs text-zinc-300">
            {u.unusual.map((x) => (
              <li key={`${x.type}${x.moneyness_pct}`}>
                {x.type} near {x.strike_near.toLocaleString("en-IN")}: {pct(x.share_of_volume)} of the expiry&apos;s volume against a usual{" "}
                {pct(x.usual_share)} (z {x.z})
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-zinc-400">
            Nothing unusual in the {u.expiry} expiry on {u.date}, against the same point before expiry in the last {u.cycles_compared} expiries.
          </p>
        )
      ) : (
        <p className="mt-1 text-xs text-zinc-500">{u.reason}</p>
      )}
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-600">{u.note}</p>

      <h3 className="mt-4 text-sm font-medium text-zinc-100">Does NIFTY show manipulation footprints on expiry days?</h3>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="py-1 font-medium">Expiry vs other days</th>
              <th className="py-1 text-right font-medium">Morning move reversed</th>
              <th className="py-1 text-right font-medium">Last-30-min move</th>
              <th className="py-1 text-right font-medium">Close pinned at a strike</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums text-zinc-300">
            <Footprint label="All since 2018" c={f.all} />
            <Footprint label="Before 2023" c={f.before_jan_2023} />
            <Footprint label="Jan 2023 – Mar 2025" c={f.jan_2023_to_mar_2025} />
            <Footprint label="Since Apr 2025" c={f.after_mar_2025} />
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">
        Jan 2023 – Mar 2025 is the period SEBI&apos;s July 2025 interim order against Jane Street covers (it concerned Bank Nifty, and the
        allegations are contested). |z| or |t| of 2 or more is highlighted; with twelve comparisons, one near 2 is what chance produces.{" "}
        {f.caveat}
      </p>
    </Panel>
  );
}

export function KnowledgeCard({ knowledge }: { knowledge: Principle[] }) {
  const sections = Array.from(new Set(knowledge.map((k) => k.section)));
  return (
    <Panel className="p-4">
      <div className="flex flex-col gap-4">
        {sections.map((s) => (
          <div key={s}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">{s}</div>
            <div className="mt-1 flex flex-col gap-1.5">
              {knowledge.filter((k) => k.section === s).map((k) => (
                <details key={k.id} className="rounded-lg bg-zinc-950/60 px-3 py-2">
                  <summary className="cursor-pointer text-sm text-zinc-200">{k.title}</summary>
                  <p className="mt-2 text-xs leading-relaxed text-zinc-400">{k.principle}</p>
                  <p className="mt-2 text-xs leading-relaxed text-zinc-300">
                    <span className="font-semibold">For you: </span>{k.for_you}
                  </p>
                  <ul className="mt-2 list-disc pl-4 text-[11px] leading-relaxed text-zinc-600">
                    {k.sources.map((src) => <li key={src}>{src}</li>)}
                  </ul>
                </details>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function MarketTab({ data }: { data: MarketContext | null }) {
  if (!data) return <Offline what="Market context" />;
  return (
    <>
      <section>
        <SectionLabel hint="attribution by association, not a cause">Why it moved</SectionLabel>
        <WhyItMovedCard today={data.today} />
      </section>
      {data.studies && (
        <>
          <section>
            <SectionLabel hint="every option bought is one someone sold">Who is on the other side</SectionLabel>
            <WhoWinsCard studies={data.studies} today={data.today} />
          </section>
          <section>
            <SectionLabel hint="statistics about the market, not evidence against anyone">Expiry days and unusual activity</SectionLabel>
            <ExpiryCard studies={data.studies} today={data.today} />
          </section>
        </>
      )}
      <section>
        <SectionLabel hint="principles with their sources — docs/MARKET_RESEARCH.md">What the research says</SectionLabel>
        <KnowledgeCard knowledge={data.knowledge} />
      </section>
    </>
  );
}
