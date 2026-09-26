"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { ChartCandle, ChartData, ChartZone } from "@/lib/api";
import { Offline, Panel } from "./ui";

/** Where NIFTY stands, and what close would change the call.
 *
 *  The Today tab asks one question — what is the call, and what would change
 *  it — and the chart draws the second half of it: the candles and moving
 *  averages, the previous session's high and low (what the breakout and
 *  breakdown rules are judged against), the price now, and, in a "day's
 *  close" column, the bands the close would have to land in for each pattern
 *  to form. Beneath it, a strip marks the days each of those patterns formed.
 *
 *  Interactive like a charting site: 15m / 4H / 1D, drag (or swipe) to scroll
 *  back, pinch or −/+ to zoom, a crosshair that reads the price under the
 *  pointer, and layers that switch on and off. Every candle, EMA and change
 *  is computed in Python (/api/chart); this only places them.
 *
 *  Drawn at the box's real width in pixels, so text stays readable and the
 *  candle count follows the screen instead of a wide SVG scrolling sideways. */

const EMA20 = "#60a5fa";
const EMA50 = "#c084fc";
const UP = "#34d399";
const DOWN = "#fb7185";
const ZONE = "#fbbf24";
const CROSS = "#818cf8"; // indigo: interaction (DESIGN §2)

type Tf = "15m" | "4h" | "1d";
const TFS: { key: Tf; label: string; name: string }[] = [
  { key: "15m", label: "15m", name: "15-minute" },
  { key: "4h", label: "4H", name: "4-hour" },
  { key: "1d", label: "1D", name: "Daily" },
];
const TF_KEY = "todayChart.tf";

// The timeframe is a per-viewer preference, kept in this browser's storage
// (and in memory where storage is unavailable). The server always renders 4H.
let chosenTf: Tf | null = null;
const tfListeners = new Set<() => void>();
const isTf = (v: unknown): v is Tf => v === "15m" || v === "4h" || v === "1d";
function readTf(): Tf {
  if (chosenTf) return chosenTf;
  try {
    const v = localStorage.getItem(TF_KEY);
    return isTf(v) ? v : "4h";
  } catch { return "4h"; }
}
function writeTf(v: Tf) {
  chosenTf = v;
  try { localStorage.setItem(TF_KEY, v); } catch { /* remembered for this visit only */ }
  tfListeners.forEach((f) => f());
}
function subscribeTf(f: () => void) {
  tfListeners.add(f);
  return () => { tfListeners.delete(f); };
}
const MIN_SPAN = 12;

const fmt = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const signedPts = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 1 })}`;
const signedPct = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (d: string) => `${Number(d.slice(8, 10))} ${MONTHS[Number(d.slice(5, 7)) - 1]}`;
/** "09:15–13:15" or "13:15–15:30" for a 4-hour block's start. */
const block = (t: string) => (t.slice(11, 16) === "13:15" ? "13:15–15:30" : "09:15–13:15");
const when = (tf: Tf, t: string) => (tf === "4h" ? block(t) : tf === "15m" ? t.slice(11, 16) : "");

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

type Bar = Omit<ChartCandle, "ema20" | "ema50" | "day_close"> & {
  ema20?: number; ema50?: number; day_close?: boolean; live?: boolean;
};

function Toggle({ on, onClick, children, label }: { on: boolean; onClick: () => void; children: ReactNode; label: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} aria-label={label}
      className={`flex items-center gap-1.5 rounded px-1 py-0.5 transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 ${on ? "" : "opacity-40"}`}>
      {children}
    </button>
  );
}

const BTN = "rounded-md border border-zinc-800 px-2 py-0.5 font-mono text-[11px] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 disabled:opacity-30";

export function TodayChart({ data }: { data: ChartData | null }) {
  if (!data || data.candles.length === 0) return <Offline what="Price chart" />;
  return <ChartView data={data} />;
}

function ChartView({ data }: { data: ChartData }) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [w, setW] = useState(0);
  const tf = useSyncExternalStore(subscribeTf, readTf, () => "4h" as Tf);
  const [span, setSpan] = useState<number | null>(null); // null: fit the screen
  const [end, setEnd] = useState(0); // candles hidden to the right; 0 = up to now
  const [hover, setHover] = useState<number | null>(null);
  const [hoverY, setHoverY] = useState<number | null>(null);
  const [show, setShow] = useState({ ema20: true, ema50: true, bands: true });
  const drag = useRef<{ x0: number; end0: number; moved: boolean } | null>(null);
  const carry = useRef(0); // sideways-swipe distance not yet a whole candle

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
  }, []);

  const choose = (next: Tf) => {
    writeTf(next); setSpan(null); setEnd(0); setHover(null);
  };

  // --- the series on screen -------------------------------------------------
  const picked: ChartCandle[] | undefined = tf === "15m" ? data.m15 : tf === "1d" ? data.daily : data.candles;
  const series: ChartCandle[] = picked && picked.length ? picked : data.candles;
  const liveBar = (tf === "15m" ? data.live_m15 : tf === "1d" ? data.live_day : data.live) ?? null;
  const full: Bar[] = [...series];
  if (liveBar) full.push({ ...liveBar, change_pct: liveBar.change_pct ?? null, live: liveBar.provisional });
  const n = full.length;

  const phone = w > 0 && w < 400;
  const fit = phone ? 30 : w < 760 ? 45 : 60;
  const shown = Math.max(Math.min(MIN_SPAN, n), Math.min(n, span ?? fit));
  const off = Math.max(0, Math.min(n - shown, end));
  const bars = full.slice(n - off - shown, n - off);
  const atLatest = off === 0;
  const tfName = TFS.find((t) => t.key === tf)!.name;

  const ref = data.levels.reference;
  const certain = data.zones.filter((z) => z.certain).slice(0, 4);
  const lanes = show.bands ? certain : [];
  const inPlay = [...new Map([...certain, ...data.zones].map((z) => [z.strategy, z.label])).entries()].slice(0, 4);
  const formedOn = new Map<string, Set<string>>();
  data.formed.forEach((f) => {
    if (!formedOn.has(f.strategy)) formedOn.set(f.strategy, new Set());
    formedOn.get(f.strategy)!.add(f.date);
  });

  // --- geometry (pixels) ----------------------------------------------------
  const W = Math.max(w, 300);
  const axisW = 60;
  const colW = show.bands ? (phone ? 40 : w < 760 ? 64 : 76) : 0;
  const H = phone ? 230 : 290;
  const padT = 18, padB = 20;
  const plotL = 2, plotR = W - axisW - colW - (colW ? 10 : 4);
  const colL = plotR + 6, colR = colW ? colL + colW : plotR;
  const slot = (plotR - plotL) / Math.max(1, bars.length);
  const bw = Math.max(1.5, Math.min(9, slot * 0.62));
  const x = (i: number) => plotL + i * slot + slot / 2;

  // Pinch (a trackpad sends it as ctrl+wheel) zooms; a sideways swipe scrolls.
  // Plain vertical scrolling is left to the page.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey) {
        e.preventDefault();
        setSpan((s) => Math.max(MIN_SPAN, Math.min(n, Math.round((s ?? shown) * Math.exp(e.deltaY * 0.01)))));
      } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        carry.current += e.deltaX / slot;
        const steps = Math.trunc(carry.current);
        if (steps) {
          carry.current -= steps;
          setEnd((v) => Math.max(0, Math.min(n - shown, v - steps)));
          setHover(null);
        }
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [slot, n, shown]);


  // The price range: the candles on screen, and — at the latest candles —
  // the levels and bands that belong to today. Scrolled back into history,
  // today's levels would only squash the old candles.
  const values = bars.flatMap((b) => [b.low, b.high,
    ...(show.ema20 && b.ema20 != null ? [b.ema20] : []), ...(show.ema50 && b.ema50 != null ? [b.ema50] : [])]);
  if (atLatest) values.push(data.levels.prev_high, data.levels.prev_low, ref, ...lanes.map((z) => z.edge ?? ref));
  const lo0 = Math.min(...values), hi0 = Math.max(...values);
  const pad = (hi0 - lo0) * 0.06 || 1;
  const lo = lo0 - pad, hi = hi0 + pad;
  const y = (v: number) => padT + ((hi - v) / (hi - lo)) * (H - padT - padB);
  const clampY = (v: number) => y(Math.max(lo, Math.min(hi, v)));
  const inRange = (v: number) => v >= lo && v <= hi;

  // Axis: the price now in a solid tag, the previous high/low in quiet tags,
  // and round-number ticks only where they would not collide with those.
  const tags = [
    { v: ref, text: fmt(ref), strong: true },
    { v: data.levels.prev_high, text: fmt(data.levels.prev_high), strong: false },
    { v: data.levels.prev_low, text: fmt(data.levels.prev_low), strong: false },
  ].filter((g) => inRange(g.v));
  // Tags close together step aside rather than overprint: the price now keeps
  // its exact spot, the others move by at least a tag's height.
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
  const step = [10, 20, 25, 50, 100, 200, 250, 500, 1000].find((s) => (hi - lo) / s <= 5) ?? 1000;
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
    const px = e.clientX - box.left, py = e.clientY - box.top;
    if (px < plotL || px > plotR || py > H) { setHover(null); setHoverY(null); return; }
    setHover(Math.max(0, Math.min(bars.length - 1, Math.floor((px - plotL) / slot))));
    setHoverY(py >= padT && py <= H - padB ? py : null);
  };
  const down = (e: PointerEvent<SVGSVGElement>) => {
    drag.current = { x0: e.clientX, end0: off, moved: false };
    (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (d) {
      const dx = e.clientX - d.x0;
      if (Math.abs(dx) > 4) d.moved = true;
      if (d.moved) {
        setEnd(Math.max(0, Math.min(n - shown, d.end0 + Math.round(dx / slot))));
        setHover(null); setHoverY(null);
        return;
      }
    }
    if (e.pointerType === "mouse" || !d) pick(e);
  };
  const up = (e: PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) pick(e); // a tap reads the candle under it
  };
  const zoom = (f: number) => setSpan(Math.max(MIN_SPAN, Math.min(n, Math.round(shown * f))));
  const keys = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowLeft") {
      if ((hover ?? bars.length) === 0) setEnd(Math.min(n - shown, off + 1));
      else setHover((h) => Math.max(0, (h ?? bars.length) - 1));
    } else if (e.key === "ArrowRight") {
      if (hover === bars.length - 1 && off > 0) setEnd(off - 1);
      else setHover((h) => Math.min(bars.length - 1, (h ?? -1) + 1));
    } else if (e.key === "+" || e.key === "=") zoom(1 / 1.4);
    else if (e.key === "-") zoom(1.4);
    else if (e.key === "End") setEnd(0);
    else if (e.key === "Escape") { setHover(null); setHoverY(null); }
    else return;
    e.preventDefault();
  };
  const hb = hover != null ? bars[hover] : null;
  // A pattern forms on the day's close, so it belongs to the candle that ends there.
  const hFormed = hb?.day_close ? data.formed.filter((f) => f.date === hb.date).map((f) => f.label) : [];
  const cursorPrice = hoverY != null ? hi - ((hoverY - padT) / (H - padT - padB)) * (hi - lo) : null;

  const last = series[series.length - 1];
  const first = bars[0];
  const lastShown = bars[bars.length - 1];
  const upTo = tf === "1d" ? `the ${day(last.date)} close` : `${day(last.date)} ${when(tf, last.t)}`;
  const summary = `NIFTY ${tfName.toLowerCase()} candles to ${upTo}, now ${fmt(ref)}. EMA20 ${fmt(last.ema20)}, EMA50 ${fmt(last.ema50)}. `
    + `Previous session high ${fmt(data.levels.prev_high)}, low ${fmt(data.levels.prev_low)}. `
    + certain.map((z) => `${z.label} (${z.side}) forms on a close ${z.condition} ${z.edge != null ? fmt(z.edge) : "here"}`).join("; ") + ".";
  const emaTf = tf === "1d" ? "daily" : tf;
  const stamp = (b: Bar) => `${day(b.date)}${tf !== "1d" ? ` ${b.t.slice(11, 16)}` : ""}`;

  return (
    <Panel className="p-3">
      {/* controls: timeframe, back to now, zoom */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 px-1">
        <div role="group" aria-label="Timeframe" className="flex rounded-md border border-zinc-800 p-0.5">
          {TFS.map((t) => (
            <button key={t.key} type="button" onClick={() => choose(t.key)} aria-pressed={tf === t.key}
              className={`rounded px-2.5 py-0.5 font-mono text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 ${
                tf === t.key ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          {!atLatest && (
            <button type="button" onClick={() => { setEnd(0); setHover(null); }} className={BTN}>Latest →</button>
          )}
          <button type="button" onClick={() => zoom(1.4)} disabled={shown >= n} aria-label="Zoom out" className={BTN}>−</button>
          <button type="button" onClick={() => zoom(1 / 1.4)} disabled={shown <= MIN_SPAN} aria-label="Zoom in" className={BTN}>+</button>
        </div>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[11px]">
        <span className="text-zinc-400">
          {tfName} · {atLatest ? <>to {upTo}</> : <>{stamp(first)} – {stamp(lastShown)}</>}
          {atLatest && liveBar?.provisional && (
            <span className="text-zinc-300"> · {tf === "1d" ? "today" : when(tf, liveBar.t)} forming (provisional)</span>
          )}
        </span>
        <Toggle on={show.ema20} onClick={() => setShow((s) => ({ ...s, ema20: !s.ema20 }))} label="Show EMA20">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: EMA20 }} />
          <span className="text-zinc-500">EMA20 ({emaTf})</span>
          <span className="font-mono tabular-nums text-zinc-400">{fmt(last.ema20)}</span>
        </Toggle>
        <Toggle on={show.ema50} onClick={() => setShow((s) => ({ ...s, ema50: !s.ema50 }))} label="Show EMA50">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: EMA50 }} />
          <span className="text-zinc-500">EMA50 ({emaTf})</span>
          <span className="font-mono tabular-nums text-zinc-400">{fmt(last.ema50)}</span>
        </Toggle>
        <Toggle on={show.bands} onClick={() => setShow((s) => ({ ...s, bands: !s.bands }))} label="Show pattern bands">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ZONE, opacity: 0.35 }} />
          <span className="text-zinc-500">a pattern forms if the day&apos;s close lands here</span>
        </Toggle>
      </div>

      <div ref={wrap} className="relative w-full">
        {w > 0 && (
          <svg ref={svgRef} width={W} height={totalH} role="img" aria-label={summary} tabIndex={0}
            onPointerDown={down} onPointerMove={move} onPointerUp={up}
            onPointerLeave={() => { if (!drag.current) { setHover(null); setHoverY(null); } }}
            onKeyDown={keys}
            className="block cursor-crosshair touch-pan-y select-none rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
            {/* grid */}
            {ticks.map((t) => (
              <g key={t}>
                <line x1={plotL} x2={colR} y1={y(t)} y2={y(t)} stroke="#27272a" strokeDasharray="2 4" />
                <text x={colR + 6} y={y(t) + 3.5} fontSize="10" fill="#71717a" fontFamily="ui-monospace, monospace">{fmt(t)}</text>
              </g>
            ))}

            {/* the day's-close column: where each pattern would form */}
            {colW > 0 && (
              <>
                <rect x={colL} y={padT} width={colW} height={H - padT - padB} fill="#18181b" opacity="0.6" rx="3" />
                <text x={colL + colW / 2} y={padT - 6} fontSize="9.5" fill="#a1a1aa" textAnchor="middle">day&apos;s close</text>
                {lanes.map((z: ChartZone, k) => {
                  const laneW = (colW - 6) / lanes.length;
                  const lx = colL + 3 + k * laneW;
                  const top = clampY(z.high), bot = clampY(z.low);
                  const edgeY = z.edge != null && inRange(z.edge) ? y(z.edge) : null;
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
              </>
            )}

            {/* previous session's high and low */}
            {[data.levels.prev_high, data.levels.prev_low].filter(inRange).map((v) => (
              <line key={v} x1={plotL} x2={colR} y1={y(v)} y2={y(v)} stroke="#71717a" strokeDasharray="1 3" />
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

            {show.ema20 && <polyline points={line("ema20")} fill="none" stroke={EMA20} strokeWidth="1.5" />}
            {show.ema50 && <polyline points={line("ema50")} fill="none" stroke={EMA50} strokeWidth="1.5" />}

            {/* the price now */}
            {inRange(ref) && (
              <line x1={plotL} x2={colR} y1={y(ref)} y2={y(ref)} stroke="#e4e4e7" strokeWidth="1" strokeDasharray="4 3" opacity="0.8" />
            )}
            {placed.map((g) => (
              <g key={g.text + g.strong}>
                <rect x={colR + 2} y={g.ty - 8} width={axisW - 4} height={16} rx="3" fill={g.strong ? "#e4e4e7" : "#27272a"} />
                <text x={colR + 6} y={g.ty + 3.5} fontSize="10" fontFamily="ui-monospace, monospace"
                  fill={g.strong ? "#09090b" : "#a1a1aa"}>{g.text}</text>
              </g>
            ))}
            {!phone && atLatest && (
              <>
                {inRange(data.levels.prev_high) && <text x={plotL + 2} y={y(data.levels.prev_high) - 4} fontSize="9.5" fill="#71717a">prev high</text>}
                {inRange(data.levels.prev_low) && <text x={plotL + 2} y={y(data.levels.prev_low) + 12} fontSize="9.5" fill="#71717a">prev low</text>}
              </>
            )}

            {/* time axis */}
            {bars.map((b, i) => (i % Math.ceil(bars.length / (phone ? 3 : 6)) === 0 ? (
              <text key={`d${b.t}`} x={i === 0 ? plotL : x(i)} y={H - 5} fontSize="9.5" fill="#71717a"
                textAnchor={i === 0 ? "start" : "middle"} fontFamily="ui-monospace, monospace">
                {tf === "15m" && b.t.slice(11, 16) !== "09:15" ? b.t.slice(11, 16) : day(b.date)}
              </text>
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
                    <circle key={b.t} cx={x(i)} cy={cy} r={Math.max(2, Math.min(3.2, slot / 2.4))} fill="#d4d4d8" />
                  ) : null))}
                  <text x={colW ? colL : W - 2} y={cy + 3.5} fontSize="9.5" fill="#a1a1aa"
                    textAnchor={colW ? "start" : "end"}>{short(label, phone ? 17 : 26)}</text>
                </g>
              );
            })}

            {/* crosshair: the candle under the pointer, and the price at its height */}
            {hb && hover != null && (
              <line x1={x(hover)} x2={x(hover)} y1={padT} y2={totalH} stroke="#a1a1aa" strokeWidth="1" opacity="0.6" />
            )}
            {cursorPrice != null && hoverY != null && (
              <g pointerEvents="none">
                <line x1={plotL} x2={colR} y1={hoverY} y2={hoverY} stroke={CROSS} strokeWidth="1" strokeDasharray="3 3" opacity="0.8" />
                <rect x={colR + 2} y={hoverY - 8} width={axisW - 4} height={16} rx="3" fill={CROSS} />
                <text x={colR + 6} y={hoverY + 3.5} fontSize="10" fontFamily="ui-monospace, monospace" fill="#09090b">
                  {fmt(Math.round(cursorPrice * 20) / 20)}
                </text>
              </g>
            )}
          </svg>
        )}

        {hb && hover != null && (
          <div className="pointer-events-none absolute top-1 z-10 w-48 rounded-md border border-zinc-700 bg-zinc-900/95 px-2.5 py-2 text-[11px] leading-relaxed shadow-lg"
            style={{ left: Math.min(Math.max(x(hover) - 96, 0), Math.max(W - 196, 0)) }}>
            <div className="text-zinc-300">
              {day(hb.date)}{tf !== "1d" && ` · ${when(tf, hb.t)}`}{hb.live && " · forming, provisional"}
            </div>
            <div className="grid grid-cols-2 gap-x-2 font-mono tabular-nums">
              <span className="text-zinc-500">Open</span><span className="text-right text-zinc-100">{fmt(hb.open)}</span>
              <span className="text-zinc-500">High</span><span className="text-right text-zinc-100">{fmt(hb.high)}</span>
              <span className="text-zinc-500">Low</span><span className="text-right text-zinc-100">{fmt(hb.low)}</span>
              <span className="text-zinc-500">Close</span><span className="text-right text-zinc-100">{fmt(hb.close)}</span>
              {hb.change_pct != null && <><span className="text-zinc-500">Change</span><span className="text-right text-zinc-300">{signedPct(hb.change_pct)}%</span></>}
              {show.ema20 && hb.ema20 != null && <><span className="text-zinc-500">EMA20</span><span className="text-right text-zinc-300">{fmt(hb.ema20)}</span></>}
              {show.ema50 && hb.ema50 != null && <><span className="text-zinc-500">EMA50</span><span className="text-right text-zinc-300">{fmt(hb.ema50)}</span></>}
            </div>
            {hFormed.length > 0 && <div className="mt-1 text-zinc-400">Formed: {hFormed.join(", ")}</div>}
          </div>
        )}
      </div>
      <p className="mt-1 px-1 text-[10.5px] text-zinc-600">
        {phone ? "Swipe the chart to scroll back · tap a candle to read it" : "Drag to scroll back · pinch or −/+ to zoom · ←/→ step through candles"}
      </p>

      {/* The readable half: what close forms what, and how far that is. */}
      <ul className="mt-3 space-y-1.5 px-1 text-[12px]">
        {certain.map((z) => (
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
