"use client";

import { useEffect, useState } from "react";

import { type LivePatterns, get } from "@/lib/api";
import { OptionPill, TrackRecord, VERDICT_TONE } from "./PatternCards";
import { Panel, Pill, fmtPct } from "./ui";

const REFRESH_MS = 60_000;

function levels(ranges: [number, number][]) {
  return ranges.map(([a, b]) => `${a.toLocaleString("en-IN")}–${b.toLocaleString("en-IN")}`).join(" or ");
}

export function LivePatternsCard({ initial }: { initial: LivePatterns | null }) {
  const [data, setData] = useState(initial);

  useEffect(() => {
    const id = setInterval(async () => {
      const res = await get<LivePatterns>("/api/live/patterns");
      if (res.data) setData(res.data);
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  if (!data) return null;
  if (!data.candle) {
    return <Panel className="p-4 text-sm text-zinc-500">{data.message ?? "No live data."}</Panel>;
  }

  const up = (data.change_pct ?? 0) >= 0;
  return (
    <Panel emphasis="accent" className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs text-zinc-300">
          If today closed at{" "}
          <span className="font-mono tabular-nums text-zinc-100">{data.candle.close.toLocaleString("en-IN")}</span>{" "}
          <span className={`font-mono tabular-nums ${up ? "text-emerald-400" : "text-rose-400"}`}>
            ({fmtPct(data.change_pct)})
          </span>
        </p>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-zinc-500">
            {data.as_of?.slice(0, 10)} · {data.basis} IST
          </span>
          {data.provisional && <Pill tone="warn">provisional</Pill>}
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {data.patterns.length === 0 && (
          <p className="text-xs text-zinc-600">No pattern would form, and none is within 1% of forming.</p>
        )}
        {data.patterns.map((p) => (
          <div key={p.strategy} className="rounded-lg bg-zinc-950/60 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <OptionPill type={p.option_type} />
                <span className="text-sm font-medium text-zinc-100">{p.label}</span>
              </div>
              <div className="flex items-center gap-2">
                {p.would_form_now ? (
                  <Pill tone="info">would form</Pill>
                ) : (
                  <span className="font-mono text-xs tabular-nums text-zinc-400">
                    {p.points_to_trigger! > 0 ? "+" : ""}
                    {p.points_to_trigger} pts ({p.pct_to_trigger! > 0 ? "+" : ""}
                    {p.pct_to_trigger}%)
                  </span>
                )}
                {p.status && <Pill tone={VERDICT_TONE[p.status]}>{p.status}</Pill>}
              </div>
            </div>
            {p.trigger_ranges_level.length > 0 && (
              <p className="mt-1.5 text-[11px] text-zinc-500">Forms on a close of {levels(p.trigger_ranges_level)}</p>
            )}
            <div className="mt-2">
              <TrackRecord
                option={p.suggested_option ? { description: p.suggested_option } : null}
                holdout={p.holdout}
                baselineRs={p.baseline_rs}
                t={p.holdout_t_stat}
              />
            </div>
          </div>
        ))}
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">{data.note}</p>
    </Panel>
  );
}
