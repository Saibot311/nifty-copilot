import type { KronosBands, KronosRecord, KronosScore, KronosView } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

const n = (v: number | null | undefined) => (v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: 1 }));
const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${n(Math.abs(v))}`;
const hhmm = (iso: string) => iso.slice(11, 16);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const pct = (v: number | null | undefined) => (v == null ? "–" : `${v}%`);

/** The next hour's median path inside its 68% and 95% bands, drawn from the API's numbers. */
function HourChart({ fc }: { fc: KronosRecord["forecast"] }) {
  const steps = fc.steps;
  const W = 320, H = 90, P = 4;
  const lo = Math.min(fc.last_close, ...steps.map((s) => s.p2_5));
  const hi = Math.max(fc.last_close, ...steps.map((s) => s.p97_5));
  const x = (i: number) => P + (i / steps.length) * (W - 2 * P);
  const y = (v: number) => P + (1 - (v - lo) / (hi - lo || 1)) * (H - 2 * P);
  const area = (a: keyof KronosBands, b: keyof KronosBands) =>
    `M${x(0)},${y(fc.last_close)} ` + steps.map((s, i) => `L${x(i + 1)},${y(s[a])}`).join(" ") +
    " " + [...steps].reverse().map((s, i) => `L${x(steps.length - i)},${y(s[b])}`).join(" ") + ` L${x(0)},${y(fc.last_close)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 h-24 w-full" role="img"
      aria-label={`Kronos's next hour: median ${n(fc.median)}, 95% range ${n(fc.band95[0])} to ${n(fc.band95[1])}`}>
      <path d={area("p97_5", "p2_5")} fill="#818cf8" fillOpacity="0.12" />
      <path d={area("p84", "p16")} fill="#818cf8" fillOpacity="0.25" />
      <line x1={P} x2={W - P} y1={y(fc.last_close)} y2={y(fc.last_close)} stroke="#52525b" strokeDasharray="3 3" />
      <polyline fill="none" stroke="#a5b4fc" strokeWidth="2"
        points={[`${x(0)},${y(fc.last_close)}`, ...steps.map((s, i) => `${x(i + 1)},${y(s.median)}`)].join(" ")} />
    </svg>
  );
}

function Row({ label, s, sub }: { label: string; s: (KronosScore & { sessions?: number }) | null | undefined; sub?: string }) {
  return (
    <tr className="border-t border-zinc-800/70">
      <td className="py-1.5 pr-2 text-zinc-300">{label}{sub && <div className="text-[10px] text-zinc-600">{sub}</div>}</td>
      <td className="py-1.5 pr-2 text-right">{s?.sessions ?? "–"}</td>
      <td className="py-1.5 pr-2 text-right">{pct(s?.inside68_pct)}</td>
      <td className="py-1.5 pr-2 text-right">{pct(s?.inside95_pct)}</td>
      <td className="py-1.5 pr-2 text-right">{pct(s?.direction_hit_pct)}</td>
      <td className="hidden py-1.5 text-right sm:table-cell">{s?.median_abs_error != null ? `${n(s.median_abs_error)} pts` : "–"}</td>
    </tr>
  );
}

/** Kronos, an open-source AI model for candles, forecasting NIFTY beside the app's own forecast. */
export function KronosCard({ data }: { data: KronosView | null }) {
  if (!data) return <Offline what="Kronos" />;
  if (!data.available) return <Panel className="p-4 text-sm text-zinc-500">Kronos is not installed on this Mac (~/Documents/kronos).</Panel>;
  const live = data.live_latest;
  const liveOpen = live && !live.outcome;
  const nd = data.next_daily?.forecast;
  const f = data.forward;
  const h = data.hindcast;
  return (
    <Panel className="p-4">
      {liveOpen ? (
        <div className="rounded-lg bg-zinc-950/60 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-xs text-zinc-300">
              Next hour, to {hhmm(live.forecast.target ?? live.target)} · from the {hhmm(live.forecast.from_bar_close!)} close {n(live.forecast.last_close)}
            </p>
            <span className="text-[11px] text-zinc-500">written {hhmm(live.made_at)}</span>
          </div>
          <HourChart fc={live.forecast} />
          <p className="font-mono text-[11px] tabular-nums text-zinc-400">
            median {n(live.forecast.median)} (<span className={live.forecast.median_move >= 0 ? "text-emerald-400" : "text-rose-400"}>{signed(live.forecast.median_move)}</span>)
            · 68% {n(live.forecast.band68[0])}–{n(live.forecast.band68[1])} · 95% {n(live.forecast.band95[0])}–{n(live.forecast.band95[1])}
          </p>
        </div>
      ) : (
        <p className="text-[11px] text-zinc-500">The live next-hour forecast runs every 15 minutes while the market is open.</p>
      )}

      {nd && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-[0.1em] text-indigo-300">Kronos · {day(nd.target!)}</div>
            <div className="font-mono text-sm tabular-nums text-zinc-100">
              median {n(nd.median)} <span className={nd.median_move >= 0 ? "text-emerald-400" : "text-rose-400"}>({signed(nd.median_move)})</span>
            </div>
            <div className="font-mono text-[11px] tabular-nums text-zinc-500">68% {n(nd.band68[0])}–{n(nd.band68[1])} · 95% {n(nd.band95[0])}–{n(nd.band95[1])}</div>
          </div>
          <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-400">Our forecast · {day(nd.target!)}</div>
            {data.our_next ? (
              <>
                <div className="font-mono text-sm tabular-nums text-zinc-100">±{n(data.our_next.sigma_pts)} pts · lean {data.our_next.lean.side}</div>
                <div className="font-mono text-[11px] tabular-nums text-zinc-500">68% {n(data.our_next.band68[0])}–{n(data.our_next.band68[1])} · 95% {n(data.our_next.band95[0])}–{n(data.our_next.band95[1])}</div>
              </>
            ) : <div className="text-[11px] text-zinc-500">Written after tonight&apos;s job.</div>}
          </div>
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="py-1.5 pr-2 text-left font-medium">Record</th>
              <th className="py-1.5 pr-2 text-right font-medium">n</th>
              <th className="py-1.5 pr-2 text-right font-medium">In 68%</th>
              <th className="py-1.5 pr-2 text-right font-medium">In 95%</th>
              <th className="py-1.5 pr-2 text-right font-medium">Direction</th>
              <th className="hidden py-1.5 text-right font-medium sm:table-cell">Typical miss</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums text-zinc-400">
            <Row label="Kronos, next session" s={f.daily} sub={f.first_daily ? `forward, since ${day(f.first_daily)}` : "forward: first scored Monday"} />
            <Row label="Ours, same sessions" s={f.ours_same_days} sub="forward" />
            <Row label="Kronos, next hour" s={f.live} sub={f.first_live ? `forward, since ${day(f.first_live)}` : "forward: starts in the next session"} />
            <Row label="Kronos, 2024–26" s={h?.kronos} sub="past check — may include prices it was trained on" />
            <Row label="Ours, 2024–26 same days" s={h?.ours_same_days} sub="past check, width fitted on 2018–23" />
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[10px] text-zinc-600">If the bands are right, about 68% and 95% of outcomes fall inside them. Direction near 50% is a coin toss.</p>

      {(data.recent_daily.length > 0 || data.recent_live.length > 0) && (
        <ul className="mt-3 space-y-1 font-mono text-[11px] tabular-nums text-zinc-400">
          {[...data.recent_daily.map((r) => ({ ...r, label: day(r.target) })), ...data.recent_live.slice(0, 4).map((r) => ({ ...r, label: `${day(r.target)} ${hhmm(r.target)}` }))].map((r) => (
            <li key={r.label} className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-sans text-zinc-300">{r.label}</span>
              <span>closed {n(r.close)} ({signed(r.move)}) · Kronos median {n(r.median)}</span>
              <span className="flex gap-1">
                <Pill tone={r.inside68 ? "good" : r.inside95 ? "warn" : "bad"}>{r.inside68 ? "in 68%" : r.inside95 ? "in 95%" : "outside"}</Pill>
                <Pill tone={r.direction_hit ? "good" : "neutral"}>{r.direction_hit ? "direction right" : "direction wrong"}</Pill>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">{data.note}{h?.warning ? ` ${h.warning}` : ""}</p>
    </Panel>
  );
}
