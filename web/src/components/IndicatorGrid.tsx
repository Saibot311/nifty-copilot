import type { IndicatorReading } from "@/lib/api";
import { Offline, Panel } from "./ui";

const DOT: Record<IndicatorReading["read"], string> = {
  supports: "bg-emerald-400",
  conflicts: "bg-rose-400",
  neutral: "bg-zinc-600",
};

export function IndicatorGrid({ indicators }: { indicators: IndicatorReading[] | null }) {
  if (!indicators) return <Offline what="Indicators" />;

  return (
    <Panel className="divide-y divide-zinc-800/70 sm:grid sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
      {indicators.map((ind, i) => (
        <div
          key={ind.name}
          className={`flex flex-col gap-1 p-3 ${
            i % 2 === 1 ? "sm:border-l sm:border-zinc-800/70" : ""
          } ${i >= 2 ? "sm:border-t sm:border-zinc-800/70" : ""} ${
            i % 4 !== 0 ? "lg:border-l lg:border-zinc-800/70" : "lg:border-l-0"
          } ${i >= 4 ? "lg:border-t lg:border-zinc-800/70" : "lg:border-t-0"}`}
        >
          <div className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[ind.read]}`} />
            <span className="truncate text-[11px] text-zinc-500">{ind.name}</span>
          </div>
          <span className="font-mono text-[13px] leading-snug text-zinc-200 tabular-nums">
            {ind.value}
          </span>
        </div>
      ))}
    </Panel>
  );
}
