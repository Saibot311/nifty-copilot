import type { DayForecast } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function day(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return `${DAYS[(d.getDay() + 6) % 7]} ${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
}
const n = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 1 });
const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${n(Math.abs(v))}`;

/** The next session's range, written before it opens, and how past forecasts turned out. */
export function DayForecastCard({ data }: { data: DayForecast | null }) {
  if (!data) return <Offline what="The day-ahead forecast" />;
  const f = data.next?.forecast;
  const h = data.hindcast;
  const st = data.status;
  const acc = data.accuracy;
  const choice = data.learning?.latest?.choice;
  return (
    <Panel className="p-4">
      {st?.stale && (
        // The card once showed Monday's forecast into Tuesday with no word that it was old.
        <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-[12px] text-amber-200">
          No forecast for {day(st.due)} yet{f && f.target !== st.due && <> — the one below is for {day(f.target)}</>}.
          <ul className="mt-1 list-disc pl-4 text-amber-200/80">
            {st.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
      {f ? (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-zinc-200">
              {day(f.target)}: NIFTY closed <span className="font-mono tabular-nums">{n(f.prev_close)}</span> on {day(f.prev)}
            </p>
            <div className="flex items-center gap-2">
              {f.tags.includes("event") && <Pill tone="warn">event day</Pill>}
              {f.tags.includes("expiry") && <Pill tone="warn">expiry</Pill>}
              <span className="text-[11px] text-zinc-500">written {data.next!.made_at.slice(0, 16).replace("T", " ")}</span>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Expected move</div>
              <div className="font-mono text-sm tabular-nums text-zinc-100">±{n(f.sigma_pts)} pts</div>
              <div className="text-[11px] text-zinc-500">
                {f.sigma_pct.toFixed(2)}% · IV {f.iv30.toFixed(1)}%{f.iv_source && f.iv_source !== "iv30" && " (from India VIX)"}
              </div>
            </div>
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Likely range</div>
              <div className="font-mono text-sm tabular-nums text-zinc-100">{n(f.band68[0])}–{n(f.band68[1])}</div>
              <div className="text-[11px] text-zinc-500">close lands here 2 days in 3</div>
            </div>
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Wide range</div>
              <div className="font-mono text-sm tabular-nums text-zinc-100">{n(f.band95[0])}–{n(f.band95[1])}</div>
              <div className="text-[11px] text-zinc-500">close lands here 19 days in 20</div>
            </div>
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">High–low range</div>
              <div className="font-mono text-sm tabular-nums text-zinc-100">~{n(f.expected_range_pts)} pts</div>
              <div className="text-[11px] text-zinc-500">typical for this IV</div>
            </div>
          </div>
          <p className="mt-3 text-xs text-zinc-300">
            Lean: <span className={f.lean.side === "up" ? "text-emerald-400" : "text-rose-400"}>{f.lean.side}</span>{" "}
            <span className="text-zinc-500">
              — {f.lean.p_up}% of {f.lean.sessions} {f.lean.basis}. A base rate, unproven as an edge
              {h?.holdout_lean_hit_pct != null && `: on 2024–26 this lean was right ${h.holdout_lean_hit_pct}% of the time`}.
            </span>
          </p>
        </>
      ) : (
        <p className="text-sm text-zinc-500">The next forecast is written after the nightly job, before the session opens.</p>
      )}

      {(acc || choice) && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {acc && (
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2 text-[11px]">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">How it&apos;s doing · last {acc.forecasts} days</div>
              {acc.days && (
                <div className="mt-1.5 flex flex-wrap gap-1" aria-label="Each day: green in the likely range, amber only in the wide range, red outside both">
                  {acc.days.map((d) => (
                    <span key={d.day} title={`${day(d.day)}: ${d.band === "in68" ? "in the likely range" : d.band === "in95" ? "in the wide range only" : "outside both ranges"}`}
                      className={`h-2.5 w-2.5 rounded-full ${d.band === "in68" ? "bg-emerald-400" : d.band === "in95" ? "bg-amber-300" : "bg-rose-400"}`} />
                  ))}
                </div>
              )}
              {acc.inside68_n != null ? (
                <ul className="mt-1.5 space-y-0.5 text-zinc-300">
                  <li><b className="font-mono tabular-nums">{acc.inside68_n} of {acc.forecasts}</b> closes in the likely range <span className="text-zinc-500">(should be about {acc.aim68_n})</span></li>
                  <li><b className="font-mono tabular-nums">{acc.inside95_n} of {acc.forecasts}</b> in the wide range <span className="text-zinc-500">(should be nearly all, about {acc.aim95_n})</span></li>
                  <li><b className="font-mono tabular-nums">{acc.lean_n} of {acc.forecasts}</b> leans right <span className="text-zinc-500">(a coin toss gets about half)</span></li>
                </ul>
              ) : (
                <div className="mt-1 font-mono tabular-nums text-zinc-200">{acc.inside68_pct}% inside 68% · {acc.inside95_pct}% inside 95%</div>
              )}
              <div className="mt-1 text-zinc-500">{acc.plain ?? acc.width_reading}</div>
            </div>
          )}
          {choice && (
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2 text-[11px]">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">How the range is set</div>
              <div className="mt-1 text-zinc-200">From {choice.labels[choice.champion] ?? choice.champion}
                {choice.switched && <> <Pill tone="info">switched</Pill></>}</div>
              <div className="text-zinc-500">
                Every night it is compared with {Object.keys(choice.labels).length - 1} other ways of setting the range; it changes only if
                another is clearly better over the last year
                {data.learning.switches.length > 0 ? ` (changed ${data.learning.switches.length} time${data.learning.switches.length > 1 ? "s" : ""} so far)` : " (none has been so far)"}.
              </div>
            </div>
          )}
        </div>
      )}

      {data.recent.length > 0 && (
        <details className="group mt-4 rounded-lg bg-zinc-950/40">
          <summary className="flex cursor-pointer list-none flex-wrap items-baseline justify-between gap-2 px-3 py-2 text-[11px] text-zinc-400 hover:text-zinc-200">
            <span>
              <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span>
              Past forecasts{data.summary && <> · {data.summary.forecasts} so far</>}
            </span>
            {data.summary && (
              <span className="font-mono tabular-nums text-zinc-500">
                likely range {data.summary.inside68_pct}% · wide range {data.summary.inside95_pct}% · lean right {data.summary.lean_hit_pct}%
              </span>
            )}
          </summary>
          <div className="overflow-x-auto px-3 pb-2">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-[0.1em] text-zinc-500">
                  <th className="py-1 pr-2 font-medium">Day</th>
                  <th className="py-1 pr-2 text-right font-medium">Close</th>
                  <th className="py-1 pr-2 text-right font-medium">Move</th>
                  <th className="hidden py-1 pr-2 text-right font-medium sm:table-cell">Range</th>
                  <th className="py-1 pr-2 text-center font-medium">Range hit</th>
                  <th className="py-1 text-center font-medium">Lean</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums text-zinc-400">
                {data.recent.map((r) => {
                  const o = r.outcome!;
                  const band = o.inside68 ? "in" : o.inside95 ? "68%" : "95%";
                  return (
                    <tr key={r.target_day} className="border-t border-zinc-800/60 align-top" title={o.why.join(" ")}>
                      <td className="py-1 pr-2 font-sans text-zinc-300">
                        {day(r.target_day)}
                        {o.why.length > 0 && (
                          <details className="font-sans">
                            <summary className="cursor-pointer text-[10px] text-zinc-500 hover:text-zinc-300">why</summary>
                            <ul className="mt-0.5 max-w-xs space-y-0.5 text-[10px] leading-snug text-zinc-500">
                              {o.why.map((w, i) => <li key={i}>{w}</li>)}
                            </ul>
                          </details>
                        )}
                      </td>
                      <td className="py-1 pr-2 text-right">{n(o.close)}</td>
                      <td className={`py-1 pr-2 text-right ${o.move_pts > 0 ? "text-emerald-400" : o.move_pts < 0 ? "text-rose-400" : ""}`}>{signed(o.move_pts)}</td>
                      <td className="hidden py-1 pr-2 text-right sm:table-cell">{n(o.range_pts)}</td>
                      <td className="py-1 pr-2 text-center">
                        <span className={band === "in" ? "text-emerald-400" : band === "68%" ? "text-amber-300" : "text-rose-400"}
                          aria-label={band === "in" ? "inside the 68% band" : `outside the ${band} band`}>
                          {band === "in" ? "✓ likely" : band === "68%" ? "~ wide" : "✗ outside"}
                        </span>
                      </td>
                      <td className={`py-1 text-center ${o.lean_hit ? "text-emerald-400" : "text-zinc-500"}`}>{o.lean_hit ? "✓" : "✗"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      )}

      <details className="mt-2">
        <summary className="cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-300">How this works</summary>
        <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
          {h?.holdout_inside68_pct != null && <>Checked on the past before going live: with the width fitted on 2018–23, 2024–26 closes fell
          inside the 68% band {h.holdout_inside68_pct}% of the time and the 95% band {h.holdout_inside95_pct}%. </>}
          Each night the width is recalibrated from the last {data.calibration_now.window} sessions (now ×{data.calibration_now.k}), and event
          days get ×{data.calibration_now.multipliers.event} from their own record. Another way of sizing the band replaces the one in use
          only if it scores better on the last 250 sessions by a fixed margin and in both halves of them, so one lucky stretch
          cannot flip it; only the width learns, never the direction. When a forecast misses, fixed checks say why. {data.note}
        </p>
      </details>
    </Panel>
  );
}
