"use client";

import { useState } from "react";

import type { ImpliedVol } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

// One series, so one hue: the dashboard's indigo, validated against the card
// surface (lightness band, chroma, 3:1 contrast). The median is a reference,
// not a series, so it is recessive and dashed.
const LINE = "#6366f1";
const SURFACE = "#0f0f12";
const W = 600;
const H = 96;
const PAD = { top: 10, right: 4, bottom: 10, left: 4 };

function ordinal(n: number) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

function Sparkline({ data, median }: { data: ImpliedVol["last_year"]; median: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const vals = data.map((d) => d.iv_30d_pct);
  const lo = Math.min(...vals, median);
  const hi = Math.max(...vals, median);
  const x = (i: number) => PAD.left + (i / Math.max(1, data.length - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - lo) / Math.max(1e-9, hi - lo)) * (H - PAD.top - PAD.bottom);
  const path = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.iv_30d_pct).toFixed(1)}`).join("");
  const last = data.length - 1;
  const h = hover != null ? data[hover] : null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`30-day implied volatility over the past year, between ${lo}% and ${hi}%; ${data[last].iv_30d_pct}% on ${data[last].date}`}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const i = Math.round(((e.clientX - r.left) / r.width) * last);
          setHover(Math.max(0, Math.min(last, i)));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={PAD.left} x2={W - PAD.right} y1={y(median)} y2={y(median)} stroke="#52525b"
              strokeWidth={1} strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
        <path d={path} fill="none" stroke={LINE} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
              vectorEffect="non-scaling-stroke" />
        {hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} stroke="#71717a" strokeWidth={1}
                vectorEffect="non-scaling-stroke" />
        )}
        {hover != null && hover !== last && (
          <circle cx={x(hover)} cy={y(data[hover].iv_30d_pct)} r={4} fill={SURFACE} stroke={LINE} strokeWidth={2}
                  vectorEffect="non-scaling-stroke" />
        )}
        {/* Today stays marked whatever is hovered. */}
        <circle cx={x(last)} cy={y(data[last].iv_30d_pct)} r={4.5} fill={LINE} stroke={SURFACE} strokeWidth={2} />
      </svg>
      {h && (
        <div
          className="pointer-events-none absolute top-0 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-[11px] text-zinc-200 shadow-lg"
          style={{ left: `${(hover! / last) * 100}%`, transform: hover! > last / 2 ? "translateX(-105%)" : "translateX(5%)" }}
        >
          <div className="text-zinc-500">{h.date}</div>
          <div className="font-mono tabular-nums">{h.iv_30d_pct}%{h.percentile != null && ` · ${ordinal(h.percentile)} pct`}</div>
        </div>
      )}
    </div>
  );
}

export function IVCard({ data }: { data: ImpliedVol | null }) {
  if (!data) return <Offline what="Implied volatility" />;
  const { latest, last_year_stats: st, vix_check: vix, test } = data;
  const adopted = test.verdict === "CANDIDATE FILTER";

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <div className="text-[11px] text-zinc-500">30-day implied volatility, {latest.date}</div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-2xl font-semibold tabular-nums text-zinc-50">{latest.iv_30d_pct}%</span>
            {latest.percentile_1y != null && (
              <span className="text-xs text-zinc-400">{ordinal(latest.percentile_1y)} percentile of the past year</span>
            )}
          </div>
        </div>
        <dl className="flex gap-4 text-[11px]">
          {[["1-yr median", st.median], ["low", st.low], ["high", st.high]].map(([k, v]) => (
            <div key={k as string}>
              <dt className="text-zinc-500">{k}</dt>
              <dd className="font-mono tabular-nums text-zinc-200">{(v as number).toFixed(2)}%</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="mt-3">
        <Sparkline data={data.last_year} median={st.median} />
        <div className="mt-0.5 flex justify-between text-[10px] text-zinc-600">
          <span>{data.last_year[0]?.date}</span>
          <span>dashed: 1-year median</span>
          <span>{latest.date}</span>
        </div>
      </div>

      <p className="mt-3 text-xs leading-relaxed text-zinc-400">
        What options cost right now. Higher implied volatility means paying more for the same expected move; a
        buyer who pays for volatility that then fades can lose even when the index goes the right way.
      </p>

      <div className={`mt-3 rounded-lg px-3 py-2 text-xs leading-relaxed ${adopted ? "bg-emerald-500/10 text-emerald-200" : "bg-zinc-800/60 text-zinc-300"}`}>
        <div className="mb-1 flex items-center gap-2">
          <span className="font-semibold">Tested as a filter</span>
          <Pill tone={adopted ? "good" : "neutral"}>{test.verdict}</Pill>
        </div>
        {test.detail}
        <div className="mt-1 text-[10px] text-zinc-500">
          Hypothesis fixed {test.registered}: {test.hypothesis}
        </div>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
        {data.method_note} Checked against India VIX over {vix.compared_days} days: correlation {vix.level_correlation}
        {vix.median_gap_points != null && `, VIX typically ${vix.median_gap_points} points higher because it also prices the skew`}.
      </p>
    </Panel>
  );
}
