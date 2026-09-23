import type { Candle } from "@/lib/api";
import { Offline, Panel } from "./ui";

/** Candlesticks with EMA20/EMA50 overlays, drawn to scale in plain SVG.
 *  The EMAs are the same lines the EMA Pullback rule keys off, so the
 *  chart shows the structure the strategy is actually reading rather than
 *  being decoration. */

function ema(values: number[], span: number): (number | null)[] {
  const k = 2 / (span + 1);
  const out: (number | null)[] = [];
  let prev: number | null = null;
  values.forEach((v, i) => {
    prev = i === 0 ? v : v * k + (prev as number) * (1 - k);
    out.push(i < span - 1 ? null : prev);
  });
  return out;
}

export function PriceChart({ candles }: { candles: Candle[] | null }) {
  if (!candles || candles.length === 0) return <Offline what="Price chart" />;

  const bars = candles.slice(-110);
  const closes = bars.map((b) => b.close);
  const ema20 = ema(closes, 20);
  const ema50 = ema(closes, 50);

  const W = 960;
  const H = 300;
  const padL = 8;
  const padR = 58;
  const padT = 12;
  const padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const lo = Math.min(...bars.map((b) => b.low));
  const hi = Math.max(...bars.map((b) => b.high));
  const pad = (hi - lo) * 0.06 || 1;
  const yMin = lo - pad;
  const yMax = hi + pad;
  const y = (v: number) => padT + ((yMax - v) / (yMax - yMin)) * plotH;
  const slot = plotW / bars.length;
  const bw = Math.max(1.5, slot * 0.58);

  const ticks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4);

  const line = (series: (number | null)[]) =>
    series
      .map((v, i) => (v == null ? null : `${padL + i * slot + slot / 2},${y(v)}`))
      .filter(Boolean)
      .join(" ");

  const last = bars[bars.length - 1];
  const first = bars[0];
  const up = last.close >= first.close;

  const labelEvery = Math.ceil(bars.length / 6);

  return (
    <Panel className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px]">
        <span className="text-zinc-500">
          Daily · last {bars.length} sessions
        </span>
        <span className="flex items-center gap-1.5 text-zinc-400">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: "#60a5fa" }} />
          EMA20
        </span>
        <span className="flex items-center gap-1.5 text-zinc-400">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: "#c084fc" }} />
          EMA50
        </span>
        <span className={`ml-auto font-mono tabular-nums ${up ? "text-emerald-400" : "text-rose-400"}`}>
          {first.timestamp.slice(0, 10)} → {last.timestamp.slice(0, 10)}
        </span>
      </div>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full min-w-[560px]"
          role="img"
          aria-label={`Daily candles for the last ${bars.length} sessions, ${first.timestamp.slice(0, 10)} to ${last.timestamp.slice(0, 10)}, with 20- and 50-day moving averages. Closed at ${last.close.toLocaleString("en-IN")}, ${up ? "above" : "below"} where the window began.`}
        >
          {ticks.map((t, i) => (
            <g key={i}>
              <line
                x1={padL}
                y1={y(t)}
                x2={padL + plotW}
                y2={y(t)}
                stroke="#27272a"
                strokeWidth="1"
                strokeDasharray="2 4"
              />
              <text
                x={padL + plotW + 6}
                y={y(t) + 3.5}
                fontSize="10"
                fill="#71717a"
                fontFamily="ui-monospace, monospace"
              >
                {Math.round(t).toLocaleString("en-IN")}
              </text>
            </g>
          ))}

          {bars.map((b, i) => {
            const cx = padL + i * slot + slot / 2;
            const rising = b.close >= b.open;
            const color = rising ? "#34d399" : "#fb7185";
            const top = y(Math.max(b.open, b.close));
            const bot = y(Math.min(b.open, b.close));
            return (
              <g key={b.timestamp}>
                <line x1={cx} y1={y(b.high)} x2={cx} y2={y(b.low)} stroke={color} strokeWidth="1" />
                <rect
                  x={cx - bw / 2}
                  y={top}
                  width={bw}
                  height={Math.max(1, bot - top)}
                  fill={color}
                  opacity={rising ? 0.85 : 0.9}
                />
              </g>
            );
          })}

          <polyline points={line(ema20)} fill="none" stroke="#60a5fa" strokeWidth="1.5" />
          <polyline points={line(ema50)} fill="none" stroke="#c084fc" strokeWidth="1.5" />

          {bars.map((b, i) =>
            i % labelEvery === 0 ? (
              <text
                key={`x${b.timestamp}`}
                x={padL + i * slot + slot / 2}
                y={H - 6}
                fontSize="9.5"
                fill="#71717a"
                textAnchor="middle"
                fontFamily="ui-monospace, monospace"
              >
                {b.timestamp.slice(5, 10)}
              </text>
            ) : null,
          )}
        </svg>
      </div>
    </Panel>
  );
}
