import type { ReactNode } from "react";
import type { DayForecastBody, KronosBands, KronosRecord, KronosScore, KronosView } from "@/lib/api";
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

/** One forecast's ranges on a scale shared with its neighbour: the wide (95%) band light, the likely (68%) band
 *  darker, Kronos's median a bright tick, the last close dashed. Positions are only scaled from the API's numbers. */
function RangeRow({ label, tone, lo, hi, last, b68, b95, median, children }: {
  label: string; tone: "kronos" | "ours"; lo: number; hi: number; last: number;
  b68: [number, number]; b95: [number, number]; median?: number; children: ReactNode;
}) {
  const span = hi - lo || 1;
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / span) * 100))}%`;
  const wid = (a: number, b: number) => `${Math.max(0.8, ((b - a) / span) * 100)}%`;
  const c = tone === "kronos"
    ? { wide: "bg-indigo-400/20", mid: "bg-indigo-400/50", label: "text-indigo-300" }
    : { wide: "bg-zinc-400/15", mid: "bg-zinc-400/40", label: "text-zinc-400" };
  return (
    <div className="rounded-lg bg-zinc-950/60 px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className={`text-[10px] font-semibold uppercase tracking-[0.1em] ${c.label}`}>{label}</span>
        <span className="font-mono text-sm tabular-nums text-zinc-100">{children}</span>
      </div>
      <div className="relative mt-2 h-3" role="img"
        aria-label={`${label}: likely range ${n(b68[0])} to ${n(b68[1])}, wide range ${n(b95[0])} to ${n(b95[1])}, last close ${n(last)}`}>
        <div className="absolute inset-x-0 top-1/2 h-px bg-zinc-800" />
        <div className={`absolute top-0.5 h-2 rounded-sm ${c.wide}`} style={{ left: pos(b95[0]), width: wid(b95[0], b95[1]) }} />
        <div className={`absolute top-0.5 h-2 rounded-sm ${c.mid}`} style={{ left: pos(b68[0]), width: wid(b68[0], b68[1]) }} />
        {median != null && <div className="absolute top-0 h-3 w-0.5 bg-indigo-200" style={{ left: pos(median) }} />}
        <div className="absolute -top-0.5 h-4 border-l border-dashed border-zinc-400" style={{ left: pos(last) }} />
      </div>
      <div className="mt-1 font-mono text-[11px] tabular-nums text-zinc-500">
        likely (68%) {n(b68[0])}–{n(b68[1])} · wide (95%) {n(b95[0])}–{n(b95[1])}
      </div>
    </div>
  );
}

/** The row a beginner needs first: Kronos and our forecast for the next session, one above the other. */
function Summary({ nd, ours }: { nd: KronosRecord["forecast"]; ours: DayForecastBody | null }) {
  const pts = [nd.last_close, ...nd.band95, ...nd.band68, ...(ours ? [...ours.band95, ...ours.band68] : [])];
  const pad = (Math.max(...pts) - Math.min(...pts)) * 0.04;
  const lo = Math.min(...pts) - pad;
  const hi = Math.max(...pts) + pad;
  return (
    <div>
      <p className="mb-2 text-xs text-zinc-300">
        Next session, {day(nd.target!)} · last close {n(nd.last_close)}{" "}
        <span className="text-zinc-500">(dashed line; the bright tick is Kronos&apos;s median)</span>
      </p>
      <div className="grid gap-2">
        <RangeRow label="Kronos (AI)" tone="kronos" lo={lo} hi={hi} last={nd.last_close} b68={nd.band68} b95={nd.band95} median={nd.median}>
          median {n(nd.median)}{" "}
          <span className={nd.median_move >= 0 ? "text-emerald-400" : "text-rose-400"}>({signed(nd.median_move)})</span>
        </RangeRow>
        {ours ? (
          <RangeRow label="Our forecast" tone="ours" lo={lo} hi={hi} last={nd.last_close} b68={ours.band68} b95={ours.band95}>
            expects ±{n(ours.sigma_pts)} pts · lean {ours.lean.side}
          </RangeRow>
        ) : (
          <div className="rounded-lg bg-zinc-950/60 px-3 py-2.5 text-[11px] text-zinc-500">
            Our forecast for {day(nd.target!)}: written after tonight&apos;s job.
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, s, sub }: { label: string; s: (KronosScore & { sessions?: number }) | null | undefined; sub?: string }) {
  return (
    <tr className="border-t border-zinc-800/70 align-top">
      <td className="py-1.5 pr-2 font-sans text-zinc-300">
        {label}
        {sub && <div className="text-[10px] text-zinc-600">{sub}</div>}
        {s?.median_abs_error != null && <div className="text-[10px] text-zinc-500 sm:hidden">typical miss {n(s.median_abs_error)} pts</div>}
      </td>
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
    <Panel className="space-y-4 p-4">
      {nd && <Summary nd={nd} ours={data.our_next} />}

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
            · likely (68%) {n(live.forecast.band68[0])}–{n(live.forecast.band68[1])} · wide (95%) {n(live.forecast.band95[0])}–{n(live.forecast.band95[1])}
          </p>
        </div>
      ) : (
        <p className="text-[11px] text-zinc-500">The live next-hour forecast runs every 15 minutes while the market is open.</p>
      )}

      <div>
        <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-500">How often the real close landed inside</h3>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] text-zinc-500">
              <th className="py-1.5 pr-2 text-left font-medium">Forecast</th>
              <th className="py-1.5 pr-2 text-right font-medium">Sessions</th>
              <th className="py-1.5 pr-2 text-right font-medium">Likely range</th>
              <th className="py-1.5 pr-2 text-right font-medium">Wide range</th>
              <th className="py-1.5 pr-2 text-right font-medium">Right way</th>
              <th className="hidden py-1.5 text-right font-medium sm:table-cell">Typical miss</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums text-zinc-400">
            <Row label="Kronos, next session" s={f.daily} sub={f.first_daily ? `forward, since ${day(f.first_daily)}` : "forward: first scored Monday"} />
            <Row label="Ours, same sessions" s={f.ours_same_days} sub="forward" />
            <Row label="Kronos, next hour" s={f.live} sub={f.first_live ? `forward, since ${day(f.first_live)}` : "forward: starts in the next session"} />
            <Row label="Kronos, 2024–26" s={h?.kronos} sub="past check" />
            <Row label="Ours, 2024–26 same days" s={h?.ours_same_days} sub="past check, width fitted on 2018–23" />
          </tbody>
        </table>
        <p className="mt-1 text-[10px] text-zinc-600">
          A fair forecast lands inside its likely range about 68% of the time and its wide range about 95%. &ldquo;Right way&rdquo; near 50% is a coin toss.
        </p>
      </div>

      {(data.recent_daily.length > 0 || data.recent_live.length > 0) && (
        <ul className="space-y-1.5 font-mono text-[11px] tabular-nums text-zinc-400">
          {[...data.recent_daily.map((r) => ({ ...r, label: day(r.target) })), ...data.recent_live.slice(0, 4).map((r) => ({ ...r, label: `${day(r.target)} ${hhmm(r.target)}` }))].map((r) => (
            <li key={r.label} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
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
      <p className="text-[10px] leading-relaxed text-zinc-600">
        {data.note}{h?.warning ? ` Past check: ${h.warning}` : ""}
      </p>
    </Panel>
  );
}
