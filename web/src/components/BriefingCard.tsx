import type { Briefing } from "@/lib/api";

export function BriefingCard({ briefing, live }: { briefing: Briefing | null; live: boolean }) {
  if (!live || !briefing) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 text-sm text-zinc-500">
        Research briefing unavailable — the backend API isn&apos;t reachable right now.
      </div>
    );
  }

  const ev = briefing.evidence;
  const chain = briefing.live_option_chain;
  const signal = briefing.signal;

  const netTone = ev.net_read.includes("bullish")
    ? "text-emerald-400"
    : ev.net_read.includes("bearish")
      ? "text-rose-400"
      : "text-amber-400";

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-indigo-400">
          Research Briefing — {briefing.symbol}
        </div>
        <div className="text-xs text-zinc-600">as of {briefing.as_of?.slice(0, 10)}</div>
      </div>

      <p className={`mt-3 text-base font-medium ${netTone}`}>{ev.net_read}</p>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <EvidenceList title={`Bullish evidence (${ev.counts.bullish})`} items={ev.bullish} tone="good" />
        <EvidenceList title={`Bearish evidence (${ev.counts.bearish})`} items={ev.bearish} tone="bad" />
      </div>

      {ev.neutral_or_context.length > 0 && (
        <div className="mt-3">
          <EvidenceList title="Context" items={ev.neutral_or_context} tone="neutral" />
        </div>
      )}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <EvidenceList
          title="What would confirm a long setup"
          items={briefing.levels.confirmation_would_be}
          tone="neutral"
        />
        <EvidenceList
          title="What would invalidate it"
          items={briefing.levels.invalidation_would_be}
          tone="neutral"
        />
      </div>

      {signal && !signal.unavailable && (
        <div className="mt-4 rounded-lg bg-zinc-950/60 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-zinc-500">
              EMA Pullback signal:{" "}
              <span className={signal.active_today ? "text-emerald-400" : "text-zinc-400"}>
                {signal.active_today ? "ACTIVE today" : "not active today"}
              </span>
            </span>
            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-300">
              {signal.validation_status}
            </span>
          </div>
          {signal.validation_reason && (
            <p className="mt-2 text-xs leading-relaxed text-zinc-500">{signal.validation_reason}</p>
          )}
        </div>
      )}

      {chain && (
        <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
          <div className="mb-2 text-xs font-medium text-zinc-500">Live option chain</div>
          {chain.unavailable ? (
            <p className="text-xs text-zinc-500">{chain.unavailable}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Metric label="Spot" value={chain.underlying_value?.toLocaleString("en-IN")} />
                <Metric label="ATM strike" value={chain.atm_strike?.toLocaleString("en-IN")} />
                <Metric
                  label="ATM IV (C/P)"
                  value={`${chain.atm_iv?.call ?? "–"} / ${chain.atm_iv?.put ?? "–"}`}
                />
                <Metric label="PCR (OI)" value={chain.open_interest?.pcr?.toFixed(2)} />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <Metric
                  label="Max call OI (often read as resistance)"
                  value={chain.open_interest?.max_call_oi_strike?.toLocaleString("en-IN")}
                />
                <Metric
                  label="Max put OI (often read as support)"
                  value={chain.open_interest?.max_put_oi_strike?.toLocaleString("en-IN")}
                />
              </div>
              {chain.interpretation_caveat && (
                <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
                  {chain.interpretation_caveat}
                </p>
              )}
            </>
          )}
        </div>
      )}

      <p className="mt-4 text-[11px] leading-relaxed text-zinc-600">{briefing.how_to_read_this}</p>
    </div>
  );
}

function EvidenceList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "bad" | "neutral";
}) {
  const color =
    tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-zinc-500";
  return (
    <div>
      <div className={`mb-1.5 text-xs font-medium ${color}`}>{title}</div>
      {items.length === 0 ? (
        <div className="text-xs text-zinc-600">None.</div>
      ) : (
        <ul className="space-y-1 text-xs text-zinc-400">
          {items.map((item, i) => (
            <li key={i}>• {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: string | number }) {
  return (
    <div>
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className="font-mono text-sm text-zinc-200">{value ?? "–"}</div>
    </div>
  );
}
