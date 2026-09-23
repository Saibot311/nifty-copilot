import type { Briefing } from "@/lib/api";
import { Offline, Panel, Pill, Stat, fmtNum } from "./ui";

export function BriefingCard({ briefing }: { briefing: Briefing | null }) {
  if (!briefing) return <Offline what="Research briefing" />;

  const ev = briefing.evidence;
  const chain = briefing.live_option_chain;

  const bullish = ev.net_read.includes("bullish");
  const bearish = ev.net_read.includes("bearish");
  const tone = bullish ? "text-emerald-400" : bearish ? "text-rose-400" : "text-amber-400";

  return (
    <Panel className="overflow-hidden">
      <div className="border-b border-zinc-800 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className={`text-xl font-semibold tracking-tight ${tone}`}>{ev.net_read}</p>
          <div className="flex items-center gap-2">
            <Pill tone={bullish ? "good" : "neutral"}>{ev.counts.bullish} bullish</Pill>
            <Pill tone={bearish ? "bad" : "neutral"}>{ev.counts.bearish} bearish</Pill>
          </div>
        </div>
      </div>

      <div className="grid gap-5 px-5 py-4 md:grid-cols-2">
        <EvidenceList title="Bullish evidence" items={ev.bullish} tone="good" />
        <EvidenceList title="Bearish evidence" items={ev.bearish} tone="bad" />
      </div>

      {ev.neutral_or_context.length > 0 && (
        <div className="border-t border-zinc-800/70 px-5 py-4">
          <EvidenceList title="Context" items={ev.neutral_or_context} tone="muted" />
        </div>
      )}

      <div className="grid gap-5 border-t border-zinc-800/70 px-5 py-4 md:grid-cols-2">
        <EvidenceList
          title="Would confirm a long setup"
          items={briefing.levels.confirmation_would_be}
          tone="muted"
        />
        <EvidenceList
          title="Would invalidate it"
          items={briefing.levels.invalidation_would_be}
          tone="muted"
        />
      </div>

      {chain && !chain.unavailable && (
        <div className="border-t border-zinc-800/70 px-5 py-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
              Live option chain
            </span>
            <span className="text-[11px] text-zinc-600">
              {chain.expiry} · {chain.strikes_analysed} strikes
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Spot" value={fmtNum(chain.underlying_value)} />
            <Stat label="ATM strike" value={fmtNum(chain.atm_strike)} />
            <Stat
              label="ATM IV call / put"
              value={`${chain.atm_iv?.call ?? "–"} / ${chain.atm_iv?.put ?? "–"}`}
            />
            <Stat label="PCR (OI)" value={chain.open_interest?.pcr?.toFixed(2) ?? "–"} />
            <Stat
              label="Max call OI"
              value={fmtNum(chain.open_interest?.max_call_oi_strike)}
              sub="often read as resistance"
            />
            <Stat
              label="Max put OI"
              value={fmtNum(chain.open_interest?.max_put_oi_strike)}
              sub="often read as support"
            />
          </div>
          {chain.interpretation_caveat && (
            <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
              {chain.interpretation_caveat}
            </p>
          )}
        </div>
      )}

      {chain?.unavailable && (
        <div className="border-t border-zinc-800/70 px-5 py-3 text-[11px] text-zinc-600">
          {chain.unavailable}
        </div>
      )}
    </Panel>
  );
}

function EvidenceList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "bad" | "muted";
}) {
  const color = { good: "text-emerald-400", bad: "text-rose-400", muted: "text-zinc-500" }[tone];
  return (
    <div>
      <div className={`mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] ${color}`}>
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-zinc-600">None.</div>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 text-xs leading-relaxed text-zinc-400">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-zinc-700" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
