import type { ChartData } from "@/lib/api";
import { Offline, Panel } from "./ui";

/** Candlesticks with EMA20/EMA50 overlays, drawn to scale in plain SVG.
 *  The EMAs are the same lines the EMA Pullback rule keys off, so the chart
 *  shows the structure the strategy is actually reading rather than being
 *  decoration.
 *
 *  Every value — candles and both averages — comes from Python (/api/chart):
 *  the same series and the same EMA function as the indicator grid, so the
 *  lines here are the numbers printed beside them. It used to draw Yahoo's
 *  raw feed (a day late, a session missing) and compute the averages here,
 *  from the bars on screen, which neither matched the grid nor drew an EMA50
 *  before the halfway point. */
export function PriceChart({ data }: { data: ChartData | null }) {
  if (!data || data.candles.length === 0) return <Offline what="Price chart" />;

  const bars = data.candles;
  const W = 960;
  const H = 300;
  const padL = 8;
  const padR = 58;
  const padT = 12;
  const padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const lo = Math.min(...bars.map((b) => Math.min(b.low, b.ema20, b.ema50)));
  const hi = Math.max(...bars.map((b) => Math.max(b.high, b.ema20, b.ema50)));
  const pad = (hi - lo) * 0.06 || 1;
  const yMin = lo - pad;
  const yMax = hi + pad;
  const y = (v: number) => padT + ((yMax - v) / (yMax - yMin)) * plotH;
  const slot = plotW / bars.length;
  const bw = Math.max(1.5, slot * 0.58);
  const cx = (i: number) => padL + i * slot + slot / 2;

  const ticks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4);
  const line = (key: "ema20" | "ema50") => bars.map((b, i) => `${cx(i)},${y(b[key])}`).join(" ");

  const last = bars[bars.length - 1];
  const first = bars[0];
  const labelEvery = Math.ceil(bars.length / 6);

  return (
    <Panel className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px]">
        <span className="text-zinc-500">Daily · last {data.sessions} sessions</span>
        <span className="flex items-center gap-1.5 text-zinc-400">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: "#60a5fa" }} />
          EMA20 <span className="font-mono tabular-nums text-zinc-500">{last.ema20.toLocaleString("en-IN")}</span>
        </span>
        <span className="flex items-center gap-1.5 text-zinc-400">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: "#c084fc" }} />
          EMA50 <span className="font-mono tabular-nums text-zinc-500">{last.ema50.toLocaleString("en-IN")}</span>
        </span>
        <span className="ml-auto font-mono tabular-nums text-zinc-500">
          {first.date} → {data.as_of} close
        </span>
      </div>

      {/* On a phone the chart is wider than the screen and scrolls in its own
          box. Right-to-left makes that box open at the newest candles — it used
          to open on the oldest, with today off-screen. */}
      <div className="overflow-x-auto" dir="rtl">
        <div dir="ltr" className="min-w-[560px]">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full"
          role="img"
          aria-label={`Daily candles for the last ${data.sessions} sessions, ${first.date} to ${data.as_of}, with 20- and 50-day moving averages. Closed at ${last.close.toLocaleString("en-IN")}; EMA20 ${last.ema20.toLocaleString("en-IN")}, EMA50 ${last.ema50.toLocaleString("en-IN")}.`}
        >
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={padL} y1={y(t)} x2={padL + plotW} y2={y(t)} stroke="#27272a" strokeWidth="1" strokeDasharray="2 4" />
              <text x={padL + plotW + 6} y={y(t) + 3.5} fontSize="10" fill="#71717a" fontFamily="ui-monospace, monospace">
                {Math.round(t).toLocaleString("en-IN")}
              </text>
            </g>
          ))}

          {bars.map((b, i) => {
            const rising = b.close >= b.open;
            const color = rising ? "#34d399" : "#fb7185";
            const top = y(Math.max(b.open, b.close));
            const bot = y(Math.min(b.open, b.close));
            return (
              <g key={b.date}>
                <title>{`${b.date}  O ${b.open.toLocaleString("en-IN")}  H ${b.high.toLocaleString("en-IN")}  L ${b.low.toLocaleString("en-IN")}  C ${b.close.toLocaleString("en-IN")}`}</title>
                <line x1={cx(i)} y1={y(b.high)} x2={cx(i)} y2={y(b.low)} stroke={color} strokeWidth="1" />
                <rect x={cx(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} fill={color} opacity={rising ? 0.85 : 0.9} />
              </g>
            );
          })}

          <polyline points={line("ema20")} fill="none" stroke="#60a5fa" strokeWidth="1.5" />
          <polyline points={line("ema50")} fill="none" stroke="#c084fc" strokeWidth="1.5" />

          {bars.map((b, i) =>
            i % labelEvery === 0 || i === bars.length - 1 ? (
              <text key={`x${b.date}`} x={cx(i)} y={H - 6} fontSize="9.5" fill="#71717a"
                textAnchor={i === bars.length - 1 ? "end" : "middle"} fontFamily="ui-monospace, monospace">
                {b.date.slice(5)}
              </text>
            ) : null,
          )}
        </svg>
        </div>
      </div>
    </Panel>
  );
}
