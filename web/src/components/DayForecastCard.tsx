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
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Close, 2 in 3</div>
              <div className="font-mono text-sm tabular-nums text-zinc-100">{n(f.band68[0])}–{n(f.band68[1])}</div>
              <div className="text-[11px] text-zinc-500">68% band</div>
            </div>
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Close, 19 in 20</div>
              <div className="font-mono text-sm tabular-nums text-zinc-100">{n(f.band95[0])}–{n(f.band95[1])}</div>
              <div className="text-[11px] text-zinc-500">95% band</div>
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
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">Accuracy, last {acc.forecasts}</div>
              <div className="mt-1 font-mono tabular-nums text-zinc-200">
                {acc.inside68_pct}% inside 68% · {acc.inside95_pct}% inside 95%
              </div>
              <div className="text-zinc-500">
                Width ×{acc.width_ratio} of what it should be — {acc.width_reading}
                {acc.forecasts < 20 && `; too few forecasts to read yet (68% and 95% are the targets)`}.
              </div>
            </div>
          )}
          {choice && (
            <div className="rounded-lg bg-zinc-950/60 px-3 py-2 text-[11px]">
              <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">How the band is sized</div>
              <div className="mt-1 text-zinc-200">{choice.labels[choice.champion] ?? choice.champion}
                {choice.switched && <Pill tone="info">switched</Pill>}</div>
              <div className="text-zinc-500">
                {choice.reason}. Checked every night against {Object.keys(choice.labels).length - 1} other ways
                {data.learning.switches.length > 0 ? `; ${data.learning.switches.length} switch(es) so far` : "; no switch so far"}.
              </div>
            </div>
          )}
        </div>
      )}

      {data.recent.length > 0 && (
        <div className="mt-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-zinc-500">
            How the forecasts turned out
            {data.summary && <span className="font-normal normal-case tracking-normal text-zinc-500"> · {data.summary.forecasts} so far: close inside the 68% band {data.summary.inside68_pct}%, 95% band {data.summary.inside95_pct}%, lean right {data.summary.lean_hit_pct}%</span>}
          </p>
          <ul className="mt-2 space-y-2">
            {data.recent.map((r) => (
              <li key={r.target_day} className="rounded-lg bg-zinc-950/60 px-3 py-2 text-[11px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-zinc-300">{day(r.target_day)}</span>
                  <span className="font-mono tabular-nums text-zinc-400">
                    closed {n(r.outcome!.close)} ({signed(r.outcome!.move_pts)}) · range {n(r.outcome!.range_pts)} pts
                  </span>
                  <span className="flex gap-1">
                    <Pill tone={r.outcome!.inside68 ? "good" : r.outcome!.inside95 ? "warn" : "bad"}>
                      {r.outcome!.inside68 ? "in band" : r.outcome!.inside95 ? "outside 68%" : "outside 95%"}
                    </Pill>
                    <Pill tone={r.outcome!.lean_hit ? "good" : "neutral"}>lean {r.outcome!.lean_hit ? "right" : "wrong"}</Pill>
                  </span>
                </div>
                {r.outcome!.why.length > 0 && (
                  <ul className="mt-1 list-disc pl-4 text-zinc-500">
                    {r.outcome!.why.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        {h?.holdout_inside68_pct != null && <>Checked on the past before going live: with the width fitted on 2018–23, 2024–26 closes fell
        inside the 68% band {h.holdout_inside68_pct}% of the time and the 95% band {h.holdout_inside95_pct}%. </>}
        Each night the width is recalibrated from the last {data.calibration_now.window} sessions (now ×{data.calibration_now.k}), and event
        days get ×{data.calibration_now.multipliers.event} from their own record. Another way of sizing the band replaces the one in use
        only if it scores better on the last 250 sessions by a fixed margin and in both halves of them, so one lucky stretch
        cannot flip it; only the width learns, never the direction. When a forecast misses, fixed checks say why. {data.note}
      </p>
    </Panel>
  );
}
