import type { ParamSweepResult } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

function cellColor(expectancy: number | null, maxAbs: number): { bg: string; text: string } {
  if (expectancy == null || maxAbs === 0) return { bg: "rgba(113,113,122,0.15)", text: "#a1a1aa" };
  const intensity = Math.min(Math.abs(expectancy) / maxAbs, 1);
  if (expectancy >= 0) {
    return { bg: `rgba(52,211,153,${0.12 + intensity * 0.55})`, text: "#d1fae5" };
  }
  return { bg: `rgba(251,113,133,${0.12 + intensity * 0.55})`, text: "#ffe4e6" };
}

export function ParamSweepHeatmap({ result }: { result: ParamSweepResult | null }) {
  if (!result) return <Offline what="Parameter sweep" />;

  const emaSpans = [...new Set(result.grid.map((c) => c.ema_span))].sort((a, b) => a - b);
  const holdDaysOptions = [...new Set(result.grid.map((c) => c.hold_days))].sort((a, b) => a - b);
  const cellFor = (ema: number, hold: number) =>
    result.grid.find((c) => c.ema_span === ema && c.hold_days === hold);
  const maxAbs = Math.max(...result.grid.map((c) => Math.abs(c.expectancy_pct ?? 0)), 0.01);

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <div className="text-xs text-zinc-500">
          EMA Pullback robustness · expectancy per trade across {result.combinations_tested} combinations
        </div>
        <Pill tone="good">
          {result.combinations_with_positive_expectancy}/{result.combinations_tested} positive
        </Pill>
      </div>

      <div className="overflow-x-auto">
        <table className="border-separate" style={{ borderSpacing: 4 }}>
          <thead>
            <tr>
              <th className="text-[11px] font-medium text-zinc-500 text-right pr-2">
                hold ↓ / ema →
              </th>
              {emaSpans.map((ema) => (
                <th key={ema} className="text-[11px] font-medium text-zinc-500 pb-1 px-1">
                  {ema}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {holdDaysOptions.map((hold) => (
              <tr key={hold}>
                <td className="text-[11px] font-medium text-zinc-500 text-right pr-2 whitespace-nowrap">
                  {hold}d
                </td>
                {emaSpans.map((ema) => {
                  const cell = cellFor(ema, hold);
                  const { bg, text } = cellColor(cell?.expectancy_pct ?? null, maxAbs);
                  return (
                    <td key={ema}>
                      <div
                        className="rounded-md px-2 py-2 text-center font-mono text-xs min-w-[62px]"
                        style={{ background: bg, color: text }}
                        title={`ema_span=${ema}, hold_days=${hold}: ${cell?.num_trades} trades`}
                      >
                        {cell?.expectancy_pct != null
                          ? `${cell.expectancy_pct > 0 ? "+" : ""}${cell.expectancy_pct.toFixed(2)}%`
                          : "n/a"}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-zinc-600">
        Rows = holding period (trading days), columns = EMA length. Green everywhere means the edge holds up
        across nearby settings — not a fluke tuned to one exact number. Still exploratory, not validated.
      </p>
    </Panel>
  );
}
