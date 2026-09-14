import type { IndicatorReading } from "@/lib/mock-data";

const READ_DOT: Record<IndicatorReading["read"], string> = {
  supports: "bg-emerald-400",
  conflicts: "bg-rose-400",
  neutral: "bg-zinc-500",
};

export function IndicatorGrid({ indicators }: { indicators: IndicatorReading[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {indicators.map((ind) => (
        <div
          key={ind.name}
          className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3"
        >
          <div className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className={`h-1.5 w-1.5 rounded-full ${READ_DOT[ind.read]}`} />
            {ind.name}
          </div>
          <div className="mt-1 text-sm font-medium text-zinc-100">{ind.value}</div>
        </div>
      ))}
    </div>
  );
}
