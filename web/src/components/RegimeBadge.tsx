import type { Regime } from "@/lib/mock-data";

const REGIME_LABEL: Record<Regime, string> = {
  TREND_BULL: "Trending Up",
  TREND_BEAR: "Trending Down",
  RANGE: "Ranging",
  TRANSITION: "Transitioning",
};

const REGIME_STYLE: Record<Regime, string> = {
  TREND_BULL: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
  TREND_BEAR: "bg-rose-500/10 text-rose-400 ring-rose-500/30",
  RANGE: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
  TRANSITION: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30",
};

export function RegimeBadge({ regime }: { regime: Regime }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset ${REGIME_STYLE[regime]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {REGIME_LABEL[regime]}
    </span>
  );
}
