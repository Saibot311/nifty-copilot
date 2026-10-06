import type { BreakoutEvent, BreakoutLevel, BreakoutRecord, Breakouts } from "@/lib/api";
import { Offline, Panel, Pill } from "./ui";

/** Today's breakout levels: where each is, where price stands against it, its
 *  breaks today scored as they go, and how breaks of it have gone since 2015
 *  and over the last 60 sessions — always beside random levels measured the
 *  same way, because any line a 5-minute close crosses tends to stay crossed
 *  for a while, and a level means something only if it beats that.
 *
 *  Up and down are zinc, not emerald and rose (DESIGN.md §2): a direction is
 *  not money made. Every figure is the API's; this only formats. */

const n = (v: number | null | undefined, d = 1) =>
  v == null ? "–" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (v: number | null | undefined, d = 1) =>
  v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${n(Math.abs(v), d)}`;
const arrow = (d: "up" | "down") => (d === "up" ? "↑" : "↓");

function held(rec: BreakoutRecord | null, d: "up" | "down", which: "all" | "recent") {
  const s = rec?.[d]?.[which];
  return s && s.held_30_pct != null ? `${s.held_30_pct}%` : "–";
}

function Record({ lv, base, which }: { lv: BreakoutLevel; base: BreakoutRecord | null; which: "all" | "recent" }) {
  return (
    <div className="space-y-0.5">
      {(["up", "down"] as const).map((d) => {
        const s = lv.record?.[d]?.[which];
        return (
          <div key={d} title={s ? `${s.n} breaks ${d}; failed within 30 min ${s.failed_pct ?? "–"}%; median ${signed(s.median_pts_30)} pts at 30 min` : undefined}>
            <span className="text-zinc-500">{arrow(d)}</span> {held(lv.record, d, which)}
            <span className="text-zinc-600"> · any {held(base, d, which)}</span>
            {s && <span className="text-zinc-600"> · {s.n}</span>}
          </div>
        );
      })}
    </div>
  );
}

function Break({ e }: { e: BreakoutEvent }) {
  const o = e.outcome;
  return (
    <div className="text-[11px] text-zinc-400">
      {arrow(e.direction)} {e.at}
      {o.pts_30 != null ? ` · ${signed(o.pts_30)} pts at 30 min` : o.pts_15 != null ? ` · ${signed(o.pts_15)} pts at 15 min` : ""}
      {o.failed && " · closed back (failed)"}
      {e.option && (
        <span className="text-zinc-500">
          {" "}· {e.option.option_type} {e.option.strike.toLocaleString("en-IN")} ask ₹{n(e.option.ask, 2)}
          {e.option.on_time ? "" : " (priced late, not counted)"}
        </span>
      )}
    </div>
  );
}

function stateText(lv: BreakoutLevel) {
  if (lv.state.startsWith("broken")) return `${lv.state} ${lv.since ?? ""}${lv.failed ? ", failed" : ""}`;
  if (lv.state === "untouched" && lv.opened) return `opened ${lv.opened}`;
  return lv.state;
}

export function BreakoutLevelsCard({ data }: { data: Breakouts | null }) {
  if (!data) return <Offline what="Today's breakout levels" />;
  if (!data.levels.length) return <Offline what="Today's breakout levels" why="No earlier session to draw levels from." />;
  const since = data.record.since?.slice(0, 4);
  return (
    <Panel className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 text-[12px]">
        <span className="text-zinc-300">
          Session {data.session.slice(8)}/{data.session.slice(5, 7)}
          {data.bars_through && ` · 5-minute bars to ${data.bars_through}`}
          {data.last_close != null && <> · NIFTY <span className="font-mono tabular-nums">{n(data.last_close, 2)}</span></>}
        </span>
        <span className="text-zinc-500">
          record: {data.record.breaks?.toLocaleString("en-IN") ?? "–"} breaks since {since ?? "–"}, rebuilt {data.record.computed_at?.slice(0, 10) ?? "—"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead className="text-[10px] uppercase tracking-[0.08em] text-zinc-500">
            <tr className="border-b border-zinc-800">
              <th className="py-1.5 pr-3 text-left font-medium">Level</th>
              <th className="py-1.5 pr-3 text-right font-medium">Price</th>
              <th className="py-1.5 pr-3 text-right font-medium">From NIFTY</th>
              <th className="py-1.5 pr-3 text-left font-medium">Today</th>
              <th className="hidden py-1.5 pr-3 text-left font-medium sm:table-cell" title="Share of breaks still beyond the level 30 minutes later">Held 30 min, since {since}</th>
              <th className="hidden py-1.5 text-left font-medium lg:table-cell">Last 60 sessions</th>
            </tr>
          </thead>
          <tbody>
            {data.levels.map((lv) => (
              <tr key={lv.key} className="border-b border-zinc-900 align-top">
                <td className="py-2 pr-3 text-zinc-300">{lv.label}</td>
                <td className="py-2 pr-3 text-right font-mono tabular-nums text-zinc-100">{n(lv.price, 2)}</td>
                <td className="py-2 pr-3 text-right font-mono tabular-nums text-zinc-400">{signed(lv.distance_pts)}</td>
                <td className="py-2 pr-3">
                  <Pill tone={lv.state.startsWith("broken") ? (lv.failed ? "warn" : "info") : "neutral"}>{stateText(lv)}</Pill>
                  {lv.events.map((e) => <Break key={e.bar_close_at + e.direction} e={e} />)}
                </td>
                <td className="hidden py-2 pr-3 font-mono tabular-nums text-zinc-300 sm:table-cell">
                  <Record lv={lv} base={data.baseline} which="all" />
                </td>
                <td className="hidden py-2 font-mono tabular-nums text-zinc-300 lg:table-cell">
                  <Record lv={lv} base={data.baseline} which="recent" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
        &ldquo;From NIFTY&rdquo; is the last 5-minute close minus the level. &ldquo;Any&rdquo; is random levels near the last close,
        broken and scored the same way: since {since} they held 30 minutes {held(data.baseline, "up", "all")} of the time
        upward and {held(data.baseline, "down", "all")} downward, so a level only stands out if it clearly beats that, and with
        this many levels a few will by chance. {data.note}
      </p>
    </Panel>
  );
}
