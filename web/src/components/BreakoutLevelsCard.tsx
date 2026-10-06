"use client";

import { Fragment, useState } from "react";
import type { BreakoutEvent, BreakoutLevel, BreakoutSlice, Breakouts, Versus } from "@/lib/api";
import { useStored } from "@/lib/stored";
import { Offline, Panel, Pill } from "./ui";

/** Today's breakout levels as a price ladder: each level above or below NIFTY,
 *  what happened at it today in words, and how often a break of it was followed
 *  by a move of the size the reader picks within the time they pick — always
 *  beside random lines near the price broken and measured the same way,
 *  because any line a 5-minute close crosses shows price moving, and a level
 *  means something only if it beats that.
 *
 *  Up and down are zinc, not emerald and rose (DESIGN.md §2): a direction is
 *  not money made. Every figure is the API's; the controls only pick which. */

const n = (v: number | null | undefined, d = 1) =>
  v == null ? "–" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v: number | null | undefined) => (v == null ? "–" : `${n(v, 0)}%`);
const arrow = (d: "up" | "down") => (d === "up" ? "↑" : "↓");
const mins = (h: string) => (h === "5" ? "the next candle" : `${h} min`);

const VERDICT: Record<Versus, { word: string; tone: "info" | "neutral" }> = {
  more: { word: "more often than random", tone: "info" },
  less: { word: "less often than random", tone: "neutral" },
  like: { word: "like random", tone: "neutral" },
  few: { word: "too few breaks", tone: "neutral" },
};

function Chips<T extends string | number>({ id, label, options, value, onChange, fmt }: {
  id: string; label: string; options: T[]; value: T; onChange: (v: T) => void; fmt: (v: T) => string;
}) {
  return (
    <div role="radiogroup" aria-labelledby={id} className="flex flex-wrap items-center gap-1">
      <span id={id} className="mr-1 text-[11px] text-zinc-500">{label}</span>
      {options.map((o) => (
        <button key={String(o)} id={`${id}-${o}`} type="button" role="radio" aria-checked={o === value}
          onClick={() => onChange(o)}
          className={`min-h-8 rounded-md border px-2 font-mono text-[11px] tabular-nums focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:outline-none ${
            o === value ? "border-indigo-500/50 bg-indigo-500/15 text-indigo-200" : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"}`}>
          {fmt(o)}
        </button>
      ))}
    </div>
  );
}

function share(s: BreakoutSlice | undefined, h: string, i: number) {
  return { p: s?.pct[h]?.[i] ?? null, n: s?.n[h] ?? 0 };
}

function TodayBreak({ e }: { e: BreakoutEvent }) {
  const o = e.outcome;
  const went = ([["5", o.travel_5], ["15", o.travel_15], ["30", o.travel_30], ["60", o.travel_60]] as const)
    .filter(([, v]) => v != null);
  return (
    <li className="text-[11.5px] leading-relaxed text-zinc-400">
      {arrow(e.direction)} Crossed {e.direction}ward at {e.at}, close {n(e.close, 2)}.
      {went.length > 0 && <> Went furthest {went.map(([h, v]) => `${n(v, 0)} pts within ${h} min`).join(", ")}.</>}
      {o.failed && " Closed back within 30 minutes."}
      {e.option && (
        <span className="text-zinc-500">
          {" "}At-the-money {e.option.option_type} {e.option.strike.toLocaleString("en-IN")} ask ₹{n(e.option.ask, 2)}
          {e.option.on_time ? "." : " (priced late, not counted)."}
        </span>
      )}
    </li>
  );
}

function Detail({ lv, data, ti, onlyLike }: { lv: BreakoutLevel; data: Breakouts; ti: number; onlyLike: boolean }) {
  const [dir, setDir] = useState<"up" | "down">(lv.plain.watch ?? "up");
  const odds = lv.odds?.[dir];
  const base = data.baseline_odds?.[dir];
  const vs = lv.vs_random?.[dir];
  const target = data.targets[ti];
  const slices = (onlyLike ? ["like_today"] : ["all", "like_today"]) as ("all" | "like_today")[];
  const rec = lv.record?.[dir]?.all;
  const baseRec = data.baseline?.[dir]?.all;
  return (
    <div className="space-y-3 pb-3 pl-1 pr-1 pt-1 text-[12px]">
      {lv.events.length > 0 && <ul className="space-y-0.5">{lv.events.map((e) => <TodayBreak key={e.bar_close_at + e.direction} e={e} />)}</ul>}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-zinc-400">Breaks</span>
        {(["up", "down"] as const).map((d) => (
          <button key={d} id={`bo-${lv.key}-${d}`} type="button" onClick={() => setDir(d)} aria-pressed={dir === d}
            className={`min-h-8 rounded-md border px-2 text-[11px] focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:outline-none ${
              dir === d ? "border-zinc-600 bg-zinc-800 text-zinc-100" : "border-zinc-800 text-zinc-500 hover:text-zinc-300"}`}>
            {arrow(d)} {d}ward{lv.plain.watch === d ? (lv.state.startsWith("broken") ? " (today's)" : " (the way price reaches it)") : ""}
          </button>
        ))}
      </div>
      {odds && base && vs ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <caption className="pb-1.5 text-left text-[11px] text-zinc-500">
              How often price then went at least {target} pts further {dir}, from the close that broke it
            </caption>
            <thead className="text-[10px] uppercase tracking-[0.08em] text-zinc-500">
              <tr className="border-b border-zinc-800">
                <th className="py-1.5 pr-3 text-left font-medium">Within</th>
                {slices.map((s) => (
                  <th key={s} colSpan={2} className="py-1.5 pr-3 text-left font-medium">
                    {s === "all" ? "All sessions" : `Sessions that opened ${data.opened ?? "like today"}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.horizons.map((h) => (
                <tr key={h} className="border-b border-zinc-900">
                  <td className="py-1.5 pr-3 text-zinc-400">{mins(h)}</td>
                  {slices.map((s) => {
                    const me = share(odds[s], h, ti), rnd = share(base[s], h, ti);
                    const v = vs[s][h]?.[ti] ?? "few";
                    return (
                      <Fragment key={s}>
                        <td className="py-1.5 pr-2 font-mono tabular-nums text-zinc-100"
                          title={`${me.n.toLocaleString("en-IN")} breaks of this level; ${rnd.n.toLocaleString("en-IN")} of random lines`}>
                          {pct(me.p)} <span className="text-zinc-500">vs {pct(rnd.p)}</span>
                        </td>
                        <td className="py-1.5 pr-3"><Pill tone={VERDICT[v].tone}>{VERDICT[v].word}</Pill></td>
                      </Fragment>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1.5 text-[11px] text-zinc-500">
            First figure: this level. After &ldquo;vs&rdquo;: random lines near the price, broken and measured the same way.
            {` ${(odds.all.n["30"] ?? 0).toLocaleString("en-IN")} breaks ${dir} since ${data.record.since?.slice(0, 4) ?? "–"}`}
            {`, ${(odds.like_today.n["30"] ?? 0).toLocaleString("en-IN")} on sessions that opened ${data.opened ?? "like today"}.`}
          </p>
        </div>
      ) : (
        <p className="text-zinc-500">The move record is not built yet; it is rebuilt every night.</p>
      )}
      {rec && (
        <p className="text-[11.5px] text-zinc-400">
          Closed back across within 30 minutes: {pct(rec.failed_pct)} of breaks {dir}
          <span className="text-zinc-500"> (random lines {pct(baseRec?.failed_pct)})</span>.
        </p>
      )}
      {lv.beyond_random && (
        <p className="text-[11.5px] text-amber-300/80">
          This level is further from the previous close than the random lines it is compared with. Price reaches such a
          level only on a day already moving a lot, so a difference may be the day&rsquo;s, not the level&rsquo;s.
        </p>
      )}
    </div>
  );
}

export function BreakoutLevelsCard({ data }: { data: Breakouts | null }) {
  const targets = data?.targets ?? [];
  const [targetS, setTarget] = useStored("breakouts.target", "30");
  const [horizon, setHorizon] = useStored("breakouts.horizon", "30");
  const [onlyLike, setOnlyLike] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [help, setHelp] = useState(false);

  if (!data) return <Offline what="Today's breakout levels" />;
  if (!data.levels.length) return <Offline what="Today's breakout levels" why="No earlier session to draw levels from." />;
  const ti = Math.max(0, targets.indexOf(Number(targetS)));
  const target = targets[ti];
  const hz = data.horizons.includes(horizon) ? horizon : "30";
  const slice = onlyLike ? "like_today" : "all";
  const ladder = [...data.levels].sort((a, b) => b.price - a.price);
  const nowAt = ladder.findIndex((lv) => data.last_close != null && lv.price < data.last_close);
  const cut = nowAt === -1 ? ladder.length : nowAt;

  const row = (lv: BreakoutLevel) => {
    const d = lv.plain.watch;
    const me = d && lv.odds ? share(lv.odds[d][slice], hz, ti) : null;
    const rnd = d && data.baseline_odds ? share(data.baseline_odds[d][slice], hz, ti) : null;
    const v = d && lv.vs_random ? lv.vs_random[d][slice][hz]?.[ti] ?? "few" : null;
    const isOpen = open === lv.key;
    return (
      <li key={lv.key} className="border-b border-zinc-900">
        <button id={`bo-row-${lv.key}`} type="button" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : lv.key)}
          className="grid min-h-11 w-full grid-cols-[1fr_auto] items-start gap-x-3 gap-y-1 py-2 text-left hover:bg-zinc-900/60 focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:outline-none sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_minmax(0,16rem)]">
          <span className="min-w-0">
            <span className="block truncate text-[12.5px] text-zinc-200">{lv.label}</span>
            <span className="font-mono text-[12px] tabular-nums text-zinc-400">{n(lv.price, 2)}</span>
          </span>
          <span className="min-w-0 text-right text-[11.5px] leading-snug text-zinc-400 sm:text-left">
            <span className="text-zinc-300">{lv.plain.where}</span>
            <span className="block">{lv.plain.today}</span>
          </span>
          <span className="col-span-2 min-w-0 text-[11.5px] leading-snug sm:col-span-1">
            {d && me && rnd && v ? (
              <>
                <span className="text-zinc-500">{arrow(d)} {target}+ pts within {mins(hz)}: </span>
                <span className="font-mono tabular-nums text-zinc-100">{pct(me.p)}</span>
                <span className="text-zinc-500"> vs random {pct(rnd.p)} · </span>
                <span className={v === "more" ? "text-indigo-300" : "text-zinc-400"}>{VERDICT[v].word}</span>
              </>
            ) : (
              <span className="text-zinc-600">no move record yet</span>
            )}
            <span aria-hidden className="ml-1 text-zinc-600">{isOpen ? "▴" : "▾"}</span>
          </span>
        </button>
        {isOpen && <Detail lv={lv} data={data} ti={ti} onlyLike={onlyLike} />}
      </li>
    );
  };

  return (
    <Panel className="p-4">
      <div className="mb-3 space-y-1.5">
        <p className="text-[13px] text-zinc-200">
          NIFTY <span className="font-mono tabular-nums">{n(data.last_close, 2)}</span>
          {data.bars_through && <span className="text-zinc-500"> at {data.bars_through}</span>}
          {data.opened && <span className="text-zinc-500"> · opened {data.opened}</span>}
          <span className="text-zinc-400"> · {data.summary.head}.</span>
        </p>
        <p className="text-[12px] leading-relaxed text-zinc-400">{data.summary.edge}</p>
      </div>

      <div className="mb-3 flex flex-col gap-2 border-y border-zinc-800/70 py-2.5">
        <Chips id="bo-target" label="Move I need" options={targets} value={target} fmt={(t) => `${t}`}
          onChange={(t) => setTarget(String(t))} />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Chips id="bo-horizon" label="Within" options={data.horizons} value={hz} fmt={(h) => (h === "5" ? "5 min" : `${h} min`)}
            onChange={setHorizon} />
          <Chips id="bo-slice" label="Sessions" options={["all", "like"]} value={onlyLike ? "like" : "all"}
            fmt={(s) => (s === "all" ? "all since 2015" : `opened ${data.opened ?? "like today"}`)}
            onChange={(s) => setOnlyLike(s === "like")} />
        </div>
      </div>

      <ol aria-label="Levels from highest to lowest price, with NIFTY between them">
        {ladder.slice(0, cut).map(row)}
        <li aria-label="NIFTY now" className="flex items-center gap-2 border-y border-indigo-500/40 bg-indigo-500/[0.06] px-2 py-1.5 text-[12px]">
          <span className="font-medium text-indigo-200">NIFTY now</span>
          <span className="font-mono tabular-nums text-zinc-100">{n(data.last_close, 2)}</span>
          {data.bars_through && <span className="text-zinc-500">5-minute close at {data.bars_through}</span>}
        </li>
        {ladder.slice(cut).map(row)}
      </ol>

      <button id="bo-help" type="button" aria-expanded={help} onClick={() => setHelp(!help)}
        className="mt-3 min-h-8 text-[11.5px] text-zinc-400 underline decoration-zinc-700 underline-offset-2 hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:outline-none">
        {help ? "Hide" : "How to read this"}
      </button>
      {help && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[11.5px] leading-relaxed text-zinc-500">
          <li>A level is crossed when a 5-minute candle closes on the other side of it. Opening beyond a level does not count.</li>
          <li>Pick the move you need and the time you can wait. Each row then says how often, since 2015, a break of that level
            was followed by at least that move in the break&rsquo;s direction, measured from the close that broke it: the price a buyer
            entering on the break could have got.</li>
          <li>&ldquo;Random&rdquo; is the same count for random lines near the price. A line a candle closes through shows price already
            moving, so a level is worth something only if it beats that. &ldquo;More often than random&rdquo; needs a gap well beyond chance:
            with this many levels, sizes and times, some differences appear by luck.</li>
          <li>Points are counted at today&rsquo;s price: the record is kept as a share of price, so 2015&rsquo;s sessions count alike.</li>
          <li>Tap a level for every time window, sessions that opened like today, both directions, and today&rsquo;s breaks with the
            at-the-money option&rsquo;s price. The record is rebuilt every night{data.travel_as_of ? `, last ${data.travel_as_of.slice(0, 10)}` : ""}.</li>
          <li>{data.note}</li>
        </ul>
      )}
    </Panel>
  );
}
