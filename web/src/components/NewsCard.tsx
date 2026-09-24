"use client";

import { useEffect, useState } from "react";
import type { NewsView } from "@/lib/api";
import { fetchNews } from "@/lib/api";
import { Offline, Panel, SectionLabel } from "./ui";

/** What is being reported, split by when it arrived relative to the session
 *  an option buyer can act in. Not a signal — the counts are counts. */

const PHASE_ORDER = ["pre_open", "live", "post_close"] as const;

function Tone({ tone }: { tone: NewsView["windows"][string]["tone"] }) {
  const { higher, lower, unclear } = tone.pointing;
  if (!tone.of_total) return <span className="text-zinc-600">nothing yet</span>;
  return (
    <span className="font-mono tabular-nums text-zinc-400">
      {tone.market_moving} of {tone.of_total} market-moving
      {tone.market_moving > 0 && (
        <>
          {" · "}
          <span className="text-zinc-300">{higher} up</span>
          {" / "}
          <span className="text-zinc-300">{lower} down</span>
          {" / "}
          <span className="text-zinc-500">{unclear} unclear</span>
        </>
      )}
      {tone.unjudged > 0 && <span className="text-zinc-600"> · {tone.unjudged} not yet read</span>}
    </span>
  );
}

function Row({ r }: { r: NewsView["windows"][string]["rows"][number] }) {
  // Decided in Python (feed.is_moving), not re-judged here. Direction is a
  // word, not a colour: green and red are reserved for money made and lost,
  // and a headline that "reads higher" is neither.
  const moving = r.moving === true;
  const dir = moving ? "text-zinc-300" : "text-zinc-600";
  return (
    <li className="border-b border-zinc-800/50 py-2 last:border-0">
      <div className="flex items-baseline gap-2">
        <span className={`shrink-0 font-mono text-[10px] tabular-nums ${moving ? dir : "text-zinc-700"}`}>
          {r.market_moving != null ? r.market_moving.toFixed(2) : "unread"}
        </span>
        <span className={`min-w-0 text-[13px] leading-snug ${moving ? "text-zinc-200" : "text-zinc-500"}`}>
          {r.url ? (
            <a href={r.url} target="_blank" rel="noopener noreferrer"
               className="hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60">
              {r.title}
            </a>
          ) : r.title}
        </span>
      </div>
      <div className="mt-0.5 pl-[3.1rem] font-mono text-[10px] text-zinc-600">
        {r.source_name}
        {r.tier === 1 && <span className="text-zinc-500"> · primary</span>}
        {r.topic && ` · ${r.topic.replace("_", "/")}`}
        {moving && r.direction !== "unclear" && <span className={dir}> · reads {r.direction}</span>}
        {" · seen "}{r.first_seen.slice(11, 16)}
      </div>
    </li>
  );
}

export function NewsCard({ initial }: { initial?: NewsView | null }) {
  // The page's AutoRefresh keeps `initial` current; the card keeps no timer of
  // its own (DESIGN §9: one poller). It asks once only if the page had none.
  const [fallback, setFallback] = useState<NewsView | null>(null);
  useEffect(() => {
    let alive = true;
    if (!initial) fetchNews().then((r) => { if (alive && r.data) setFallback(r.data); });
    return () => { alive = false; };
  }, [initial]);
  const data = initial ?? fallback;

  if (!data) return <Offline what="Market news" />;

  return (
    <Panel className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] text-zinc-300">{data.says}</span>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {data.as_of.slice(11, 16)} IST · {data.archive.headlines.toLocaleString("en-IN")} archived
        </span>
      </div>

      {PHASE_ORDER.map((key) => {
        const w = data.windows[key];
        if (!w) return null;
        const here = data.phase === key;
        return (
          <div key={key} className="mt-3 first:mt-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-zinc-800 pb-1">
              <span className={`text-[11px] font-semibold uppercase tracking-[0.1em] ${here ? "text-zinc-300" : "text-zinc-500"}`}>
                {w.label}{here && <span className="ml-1.5 font-normal normal-case tracking-normal text-emerald-400">now</span>}
              </span>
              <span className="text-[10px]"><Tone tone={w.tone} /></span>
            </div>
            <p className="mt-1 text-[11px] text-zinc-600">
              {w.means}
              {(w.older_copy_hidden ?? 0) > 0 && ` ${w.older_copy_hidden} older stories still in the feeds are archived, not shown.`}
            </p>
            {w.rows.length > 0 ? (
              <ul className="mt-1">{w.rows.map((r) => <Row key={r.id} r={r} />)}</ul>
            ) : (
              <p className="py-2 text-[12px] text-zinc-600">Nothing archived in this window yet.</p>
            )}
          </div>
        );
      })}

      <p className="mt-3 border-t border-zinc-800 pt-2 text-[11px] leading-relaxed text-zinc-500">
        {data.note}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-600">
        Read by {data.judged_by}. The number beside each headline is its probability of being the kind of event
        that moves an index — not a probability that the market will move.
      </p>
    </Panel>
  );
}

export function NewsSection({ data }: { data: NewsView | null }) {
  return (
    <section className="min-w-0 xl:col-span-2">
      <SectionLabel hint="what is being reported — context, not a signal">
        In the news
      </SectionLabel>
      <NewsCard initial={data} />
    </section>
  );
}
