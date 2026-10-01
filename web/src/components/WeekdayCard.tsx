import type { WeekdayProfile } from "@/lib/api";
import { Offline, Panel, Pill, minus } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(2, 4)}`;

/** Points with a sign and a true minus. */
function pts(v: number | null | undefined) {
  if (v == null) return "–";
  const r = Math.round(v);
  return `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r).toLocaleString("en-IN")}`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-zinc-950/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.1em] text-zinc-500">{label}</div>
      <div className="mt-0.5 font-mono text-sm tabular-nums text-zinc-100">{value}</div>
      {sub && <div className="text-[11px] text-zinc-500">{sub}</div>}
    </div>
  );
}

/** How NIFTY moves on this weekday, point by point, and today against it. */
export function WeekdayCard({ data }: { data: WeekdayProfile | null }) {
  if (!data) return <Offline what="The weekday profile" />;
  const p = data.profile;
  if (!p) return <Panel className="p-4 text-sm text-zinc-500">Not enough past {data.weekday}s in the archive.</Panel>;
  const t = data.today;
  const todayAt = new Map((t?.path ?? []).map((x) => [x.at, x.points]));

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs text-zinc-300">
          Every {data.weekday} since {MONTHS[Number(p.since.slice(5, 7)) - 1]} {p.since.slice(0, 4)} · {p.sessions.toLocaleString("en-IN")} sessions
        </p>
        <div className="flex items-center gap-2">
          {data.expiry && <Pill tone="warn">expiry day</Pill>}
          <span className="text-[11px] text-zinc-500">
            points from the open, at {data.reference.is === "today's open" ? "today's open" : "the last close"} ({p.ref.toLocaleString("en-IN")})
          </span>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Typical range" value={`${pts(p.range).replace("+", "")} pts`}
          sub={`${p.range_pct.toFixed(2)}% of the open · all days ${pts(data.all_days?.range).replace("+", "")}`} />
        <Stat label="Went up first" value={`${p.up_first_pct}% of days`} sub={`first swing ends ~${p.first_swing_ends ?? "–"}`} />
        <Stat label="If up first" value={`${pts(p.first_up)} then ${pts(p.back_after_up == null ? null : -p.back_after_up)}`}
          sub="first swing, swing back" />
        <Stat label="If down first" value={`${pts(p.first_down == null ? null : -p.first_down)} then ${pts(p.back_after_down)}`}
          sub={`about ${p.swings_per_day ?? "–"} swings a day`} />
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.1em] text-zinc-500">
              <th className="py-1.5 pr-3 font-medium">At</th>
              <th className="py-1.5 pr-3 text-right font-medium">Typical</th>
              <th className="py-1.5 pr-3 text-right font-medium">Middle half of days</th>
              <th className="py-1.5 text-right font-medium">Today</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {p.path.map((r) => (
              <tr key={r.at} className="border-t border-zinc-800/70">
                <td className="py-1.5 pr-3 font-sans text-zinc-400">{r.at === "15:30" ? "Close" : r.at}</td>
                <td className="py-1.5 pr-3 text-right text-zinc-200">{pts(r.median)}</td>
                <td className="py-1.5 pr-3 text-right text-zinc-500">{pts(r.p25)} to {pts(r.p75)}</td>
                <td className="py-1.5 text-right text-zinc-100">{todayAt.has(r.at) ? pts(todayAt.get(r.at)) : "·"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {t && (
        <p className="mt-3 text-[11px] leading-relaxed text-zinc-400">
          Today from {t.open.toLocaleString("en-IN")}: up to {pts(t.up)}, down to {pts(-t.down)}, {pts(t.now)} at {t.through}.
          {t.swings.length > 0 && <> Swings: {t.swings.map((s, i) => (
            <span key={i} className="font-mono tabular-nums">{i ? ", " : " "}{pts(s.dir * s.points)}{s.ends ? ` by ${s.ends}` : ""}{s.done ? "" : " (running)"}</span>
          ))}.</>}
        </p>
      )}

      {data.similar && (
        <div className="mt-3 rounded-lg bg-zinc-950/60 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-zinc-500">
            Past {data.weekday}s most like today to {data.similar.through}
          </p>
          <ul className="mt-2 space-y-1 font-mono text-[11px] tabular-nums text-zinc-400">
            {data.similar.days.map((d) => (
              <li key={d.date} className="flex flex-wrap justify-between gap-x-3">
                <span className="font-sans text-zinc-300">{day(d.date)}{d.expiry ? " · expiry" : ""}</span>
                <span>{pts(d.at_last)} by {data.similar!.through}, then {pts(d.after)} to the close</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-zinc-500">{data.similar.note} Points are scaled to today&apos;s open.</p>
        </div>
      )}

      <ul className="mt-3 space-y-1.5 text-[11px] leading-relaxed text-zinc-400">
        {data.why.map((w, i) => (
          <li key={i} className="flex gap-2"><span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-zinc-600" /><span>{w}</span></li>
        ))}
      </ul>

      {data.indicators.length > 0 && (
        <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
          Can the move be seen coming? The intraday rules built to catch it, judged on 2024–26:{" "}
          {data.indicators.map((x, i) => (
            <span key={x.label}>{i ? "; " : ""}{x.label} {x.verdict} (t {minus(x.holdout_t)}, bar {minus(x.required_t)})</span>
          ))}. {data.indicators.some((x) => x.verdict === "APPROVED") ? "" : "None cleared the bar."}
        </p>
      )}
      <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">{data.note}</p>
    </Panel>
  );
}
