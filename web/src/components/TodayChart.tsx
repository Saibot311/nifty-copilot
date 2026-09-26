"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { ChartData, ChartZone } from "@/lib/api";
import { Offline, Panel } from "./ui";

/** Where NIFTY stands, and what close would change the call.
 *
 *  The Today tab asks one question — what is the call, and what would change
 *  it — and the chart now draws the second half of it: the recent candles and
 *  moving averages, the previous session's high and low (what the breakout
 *  and breakdown rules are judged against), the price now, and, in a "next
 *  close" column, the bands a close would have to land in for each pattern to
 *  form. Beneath it, a strip marks the days each of those patterns actually
 *  formed. Everything is computed in Python (/api/chart); this only places it.
 *
 *  Drawn at the box's real width in pixels, so text stays readable and the
 *  candle count follows the screen (30 on a phone, 60 on a desk) instead of a
 *  wide SVG scrolling sideways. */

const EMA20 = "#60a5fa";
const EMA50 = "#c084fc";
const UP = "#34d399";
const DOWN = "#fb7185";
const ZONE = "#fbbf24";

const fmt = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const signedPts = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 1 })}`;
const signedPct = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
// Row names for the narrow strip: whole words, never cut mid-word.
const SHORT: Record<string, string> = {
  "Prev-Day-Low Breakdown": "Prev-day low break", "Prev-Day-High Breakout": "Prev-day high break",
  "Stochastic Oversold Reversal": "Stoch. oversold", "Stochastic Overbought Reversal": "Stoch. overbought",
  "MACD Bullish Crossover": "MACD bull cross", "MACD Bearish Crossover": "MACD bear cross",
  "RSI Oversold Reversal": "RSI oversold", "RSI Overbought Reversal": "RSI overbought",
  "Bollinger Band Reversion": "Bollinger rev.", "Bollinger Upper Rejection": "Bollinger reject",
};
const short = (label: string, max: number) => {
  const base = SHORT[label] ?? label.replace(/ \(at swing (high|low)\)/, "");
  if (base.length <= max) return base;
  const cut = base.slice(0, max - 1);
  return `${cut.slice(0, cut.lastIndexOf(" ") > 4 ? cut.lastIndexOf(" ") : cut.length)}…`;
};

type Bar = { t: string; date: string; day_close?: boolean; open: number; high: number; low: number; close: number;
  ema20?: number; ema50?: number; live?: boolean };

/** "09:15–13:15" or "13:15–15:30" for a block's start. */
const block = (t: string) => (t.slice(11, 16) === "13:15" ? "13:15–15:30" : "09:15–13:15");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (d: string) => `${Number(d.slice(8, 10))} ${MONTHS[Number(d.slice(5, 7)) - 1]}`;

export function TodayChart({ data }: { data: ChartData | null }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const hasData = !!data && data.candles.length > 0;

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    // Measured at once, not only on the observer's first callback: a page
    // opened in a background tab gets no callback until it is shown, and the
    // chart would sit blank.
    setW(Math.round(el.clientWidth));
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [hasData]); // re-attach when data arrives after an offline first render

  if (!data || data.candles.length === 0) return <Offline what="Price chart" />;

  const phone = w > 0 && w < 400;
  const n = phone ? 30 : w < 760 ? 45 : 60;
  const bars: Bar[] = data.candles.slice(-n);
  if (data.live) bars.push({ t: data.live.t, date: data.live.date, open: data.live.open, high: data.live.high,
    low: data.live.low, close: data.live.close, live: true });

  const ref = data.levels.reference;
  const lanes = data.zones.filter((z) => z.certain).slice(0, 4);
  const inPlay = [...new Map([...lanes, ...data.zones].map((z) => [z.strategy, z.label])).entries()].slice(0, 4);
  const formedOn = new Map<string, Set<string>>();
  data.formed.forEach((f) => {
    if (!formedOn.has(f.strategy)) formedOn.set(f.strategy, new Set());
    formedOn.get(f.strategy)!.add(f.date);
  });

  // --- geometry (pixels) ----------------------------------------------------
  const W = Math.max(w, 300);
  const axisW = 60;
  const colW = phone ? 40 : w < 760 ? 64 : 76;
  const H = phone ? 230 : 290;
  const padT = 18, padB = 20;
  const plotL = 2, plotR = W - axisW - colW - 10;
  const colL = plotR + 6, colR = colL + colW;
  const slot = (plotR - plotL) / bars.length;
  const bw = Math.max(2, Math.min(9, slot * 0.62));
  const x = (i: number) => plotL + i * slot + slot / 2;

  const values = bars.flatMap((b) => [b.low, b.high, b.ema20 ?? b.close, b.ema50 ?? b.close]);
  values.push(data.levels.prev_high, data.levels.prev_low, ref, ...lanes.map((z) => z.edge ?? ref));
  const lo0 = Math.min(...values), hi0 = Math.max(...values);
  const pad = (hi0 - lo0) * 0.06 || 1;
  const lo = lo0 - pad, hi = hi0 + pad;
  const y = (v: number) => padT + ((hi - v) / (hi - lo)) * (H - padT - padB);
  const clampY = (v: number) => y(Math.max(lo, Math.min(hi, v)));

  // Axis: the price now in a solid tag, the previous high/low in quiet tags,
  // and round-number ticks only where they would not collide with those.
  const tags = [
    { v: ref, text: fmt(ref), strong: true },
    { v: data.levels.prev_high, text: `${fmt(data.levels.prev_high)}`, strong: false },
    { v: data.levels.prev_low, text: `${fmt(data.levels.prev_low)}`, strong: false },
  ];
  // Tags close together (the price now is often a few points from the
  // previous low) step aside rather than overprint: the price now keeps its
  // exact spot, the others move by at least a tag's height.
  const TAG_H = 17;
  const placed: { v: number; text: string; strong: boolean; ty: number }[] = [];
  for (const g of [...tags].sort((a, b) => Number(b.strong) - Number(a.strong))) {
    let ty = y(g.v);
    for (let pass = 0; pass < 3; pass++) {
      for (const o of placed) {
        if (Math.abs(ty - o.ty) < TAG_H) ty = ty <= o.ty ? o.ty - TAG_H : o.ty + TAG_H;
      }
    }
    placed.push({ ...g, ty: Math.max(padT, Math.min(H - padB, ty)) });
  }
  const step = [50, 100, 200, 250, 500, 1000].find((s) => (hi - lo) / s <= 5) ?? 1000;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
    if (placed.every((g) => Math.abs(g.ty - y(t)) > 13)) ticks.push(t);
  }

  const line = (key: "ema20" | "ema50") =>
    bars.map((b, i) => (b[key] == null ? null : `${x(i)},${y(b[key] as number)}`)).filter(Boolean).join(" ");

  const rowH = 15;
  const stripTop = H + 12;
  const totalH = stripTop + inPlay.length * rowH + (inPlay.length ? 4 : 0);

  // --- interaction ----------------------------------------------------------
  const pick = (e: PointerEvent<SVGSVGElement>) => {
    const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - box.left;
    if (px < plotL || px > plotR) return setHover(null);
    setHover(Math.max(0, Math.min(bars.length - 1, Math.floor((px - plotL) / slot))));
  };
  const keys = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? bars.length) - 1));
    else if (e.key === "ArrowRight") setHover((h) => Math.min(bars.length - 1, (h ?? -1) + 1));
    else if (e.key === "Escape") setHover(null);
    else return;
    e.preventDefault();
  };
  const hb = hover != null ? bars[hover] : null;
  // A pattern forms on the day's close, so it belongs to the block that ends there.
  const hFormed = hb?.day_close ? data.formed.filter((f) => f.date === hb.date).map((f) => f.label) : [];

  const last = data.candles[data.candles.length - 1];
  const summary = `NIFTY 4-hour candles to the ${last.date} ${block(last.t)} block, now ${fmt(ref)}. 4-hour EMA20 ${fmt(last.ema20)}, EMA50 ${fmt(last.ema50)}. `
    + `Previous session high ${fmt(data.levels.prev_high)}, low ${fmt(data.levels.prev_low)}. `
    + lanes.map((z) => `${z.label} (${z.side}) forms on a close ${z.condition} ${z.edge != null ? fmt(z.edge) : "here"}`).join("; ") + ".";

  return (
    <Panel className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px]">
        <span className="text-zinc-400">
          4-hour · to {day(last.date)} {block(last.t)}{data.live && <span className="text-zinc-300"> · {block(data.live.t)} forming (provisional)</span>}
        </span>
        <span className="flex items-center gap-1.5 text-zinc-500">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: EMA20 }} />EMA20 (4h){" "}
          <span className="font-mono tabular-nums text-zinc-400">{fmt(last.ema20)}</span>
        </span>
        <span className="flex items-center gap-1.5 text-zinc-500">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: EMA50 }} />EMA50 (4h){" "}
          <span className="font-mono tabular-nums text-zinc-400">{fmt(last.ema50)}</span>
        </span>
        <span className="flex items-center gap-1.5 text-zinc-500">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ZONE, opacity: 0.35 }} />
          a pattern forms if the day&apos;s close lands here
        </span>
      </div>

      <div ref={wrap} className="relative w-full">
        {w > 0 && (
          <svg width={W} height={totalH} role="img" aria-label={summary} tabIndex={0}
            onPointerMove={pick} onPointerLeave={() => setHover(null)} onKeyDown={keys}
            className="block touch-pan-y rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
            {/* grid */}
            {ticks.map((t) => (
              <g key={t}>
                <line x1={plotL} x2={colR} y1={y(t)} y2={y(t)} stroke="#27272a" strokeDasharray="2 4" />
                <text x={colR + 6} y={y(t) + 3.5} fontSize="10" fill="#71717a" fontFamily="ui-monospace, monospace">{fmt(t)}</text>
              </g>
            ))}

            {/* the next-close column: where each pattern would form */}
            <rect x={colL} y={padT} width={colW} height={H - padT - padB} fill="#18181b" opacity="0.6" rx="3" />
            <text x={colL + colW / 2} y={padT - 6} fontSize="9.5" fill="#a1a1aa" textAnchor="middle">day&apos;s close</text>
            {lanes.map((z: ChartZone, k) => {
              const laneW = (colW - 6) / lanes.length;
              const lx = colL + 3 + k * laneW;
              const top = clampY(z.high), bot = clampY(z.low);
              const edgeY = z.edge != null ? y(z.edge) : null;
              return (
                <g key={`${z.strategy}${z.low}`}>
                  <title>{`${z.label} (${z.side}): forms on a close ${z.condition} ${z.edge != null ? fmt(z.edge) : "this level"}`}</title>
                  <rect x={lx} y={top} width={laneW - 2} height={Math.max(2, bot - top)} fill={ZONE} opacity="0.22" rx="2" />
                  {edgeY != null && <line x1={lx} x2={lx + laneW - 2} y1={edgeY} y2={edgeY} stroke={ZONE} strokeWidth="2" />}
                  {edgeY != null && (
                    <text x={lx + (laneW - 2) / 2} y={z.condition === "at or above" ? edgeY - 4 : edgeY + 11}
                      fontSize="10" fill={ZONE} textAnchor="middle">{z.side === "call" ? "▲" : "▼"}</text>
                  )}
                </g>
              );
            })}

            {/* previous session's high and low */}
            {[data.levels.prev_high, data.levels.prev_low].map((v, k) => (
              <line key={k} x1={plotL} x2={colR} y1={y(v)} y2={y(v)} stroke="#71717a" strokeDasharray="1 3" />
            ))}

            {/* candles */}
            {bars.map((b, i) => {
              const color = b.close >= b.open ? UP : DOWN;
              const top = y(Math.max(b.open, b.close)), bot = y(Math.min(b.open, b.close));
              return (
                <g key={b.t + (b.live ? "live" : "")} opacity={hover != null && hover !== i ? 0.55 : 1}>
                  <line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={color} strokeWidth="1" />
                  <rect x={x(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)}
                    fill={b.live ? "none" : color} stroke={color} strokeWidth={b.live ? 1.5 : 0}
                    strokeDasharray={b.live ? "3 2" : undefined} />
                </g>
              );
            })}

            <polyline points={line("ema20")} fill="none" stroke={EMA20} strokeWidth="1.5" />
            <polyline points={line("ema50")} fill="none" stroke={EMA50} strokeWidth="1.5" />

            {/* the price now */}
            <line x1={plotL} x2={colR} y1={y(ref)} y2={y(ref)} stroke="#e4e4e7" strokeWidth="1" strokeDasharray="4 3" opacity="0.8" />
            {placed.map((g) => (
              <g key={g.text + g.strong}>
                <rect x={colR + 2} y={g.ty - 8} width={axisW - 4} height={16} rx="3"
                  fill={g.strong ? "#e4e4e7" : "#27272a"} />
                <text x={colR + 6} y={g.ty + 3.5} fontSize="10" fontFamily="ui-monospace, monospace"
                  fill={g.strong ? "#09090b" : "#a1a1aa"}>{g.text}</text>
              </g>
            ))}
            {!phone && (
              <>
                <text x={plotL + 2} y={y(data.levels.prev_high) - 4} fontSize="9.5" fill="#71717a">prev high</text>
                <text x={plotL + 2} y={y(data.levels.prev_low) + 12} fontSize="9.5" fill="#71717a">prev low</text>
              </>
            )}

            {/* dates */}
            {bars.map((b, i) => (i % Math.ceil(bars.length / (phone ? 3 : 6)) === 0 ? (
              <text key={`d${b.t}`} x={i === 0 ? plotL : x(i)} y={H - 5} fontSize="9.5" fill="#71717a"
                textAnchor={i === 0 ? "start" : "middle"} fontFamily="ui-monospace, monospace">{b.date.slice(5)}</text>
            ) : null))}

            {inPlay.length > 0 && (
              <text x={plotL} y={stripTop - 1} fontSize="9" fill="#52525b">days each formed</text>
            )}

            {/* the strip: days each pattern in play actually formed */}
            {inPlay.map(([strategy, label], r) => {
              const cy = stripTop + r * rowH + rowH / 2;
              const days = formedOn.get(strategy) ?? new Set<string>();
              return (
                <g key={strategy}>
                  <line x1={plotL} x2={plotR} y1={cy} y2={cy} stroke="#27272a" />
                  {bars.map((b, i) => (b.day_close && days.has(b.date) ? (
                    <circle key={b.t} cx={x(i)} cy={cy} r={Math.min(3.2, slot / 2.4)} fill="#d4d4d8" />
                  ) : null))}
                  <text x={colL} y={cy + 3.5} fontSize="9.5" fill="#a1a1aa">{short(label, phone ? 17 : 26)}</text>
                </g>
              );
            })}

            {/* crosshair */}
            {hb && hover != null && (
              <line x1={x(hover)} x2={x(hover)} y1={padT} y2={totalH} stroke="#a1a1aa" strokeWidth="1" opacity="0.6" />
            )}
          </svg>
        )}

        {hb && hover != null && (
          <div className="pointer-events-none absolute top-1 z-10 w-48 rounded-md border border-zinc-700 bg-zinc-900/95 px-2.5 py-2 text-[11px] leading-relaxed shadow-lg"
            style={{ left: Math.min(Math.max(x(hover) - 96, 0), Math.max(W - 196, 0)) }}>
            <div className="text-zinc-300">{day(hb.date)} · {block(hb.t)}{hb.live && " · forming, provisional"}</div>
            <div className="grid grid-cols-2 gap-x-2 font-mono tabular-nums">
              <span className="text-zinc-500">Open</span><span className="text-right text-zinc-100">{fmt(hb.open)}</span>
              <span className="text-zinc-500">High</span><span className="text-right text-zinc-100">{fmt(hb.high)}</span>
              <span className="text-zinc-500">Low</span><span className="text-right text-zinc-100">{fmt(hb.low)}</span>
              <span className="text-zinc-500">Close</span><span className="text-right text-zinc-100">{fmt(hb.close)}</span>
              {hb.ema20 != null && <><span className="text-zinc-500">EMA20</span><span className="text-right text-zinc-300">{fmt(hb.ema20)}</span></>}
              {hb.ema50 != null && <><span className="text-zinc-500">EMA50</span><span className="text-right text-zinc-300">{fmt(hb.ema50)}</span></>}
            </div>
            {hFormed.length > 0 && <div className="mt-1 text-zinc-400">Formed: {hFormed.join(", ")}</div>}
          </div>
        )}
      </div>

      {/* The readable half: what close forms what, and how far that is. */}
      <ul className="mt-3 space-y-1.5 px-1 text-[12px]">
        {lanes.map((z) => (
          <li key={`${z.strategy}${z.low}`} className="flex flex-wrap items-baseline gap-x-2 text-zinc-300">
            <span className="text-amber-300">{z.side === "call" ? "▲" : "▼"}</span>
            <span className="text-zinc-100">{z.label}</span>
            <span className="text-zinc-500">buys a {z.side} ·</span>
            <span>
              {z.edge == null
                ? "forms if the close stays around here"
                : <>forms on a close {z.condition} <span className="font-mono tabular-nums text-zinc-100">{fmt(z.edge)}</span></>}
            </span>
            {z.edge != null && (
              <span className="font-mono text-[11px] tabular-nums text-zinc-500">
                {signedPts(z.distance_pts)} pts ({signedPct(z.distance_pct)}%) from {fmt(ref)}
              </span>
            )}
          </li>
        ))}
      </ul>
      {data.zones.some((z) => !z.certain) && (
        <details className="mt-2 px-1">
          <summary className="cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-400">
            Also possible, depending on how the day trades (not the close alone)
          </summary>
          <ul className="mt-1 space-y-1 text-[11px] text-zinc-400">
            {data.zones.filter((z) => !z.certain).map((z) => (
              <li key={`${z.strategy}${z.low}`}>
                {z.label} ({z.side}): a close between <span className="font-mono tabular-nums">{fmt(z.low)}–{fmt(z.high)}</span>
                {z.needs.length > 0 ? ` with ${z.needs.join(", ")}` : ", if the day's open, high and low also fit"}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="mt-2 px-1 text-[11px] leading-relaxed text-zinc-500">
        {data.note} The strip under the candles marks the days each of these patterns formed.
      </p>
    </Panel>
  );
}
