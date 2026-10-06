"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { IndicatorHistory, IndicatorTile, Indicators, Versus } from "@/lib/api";
import { useStored } from "@/lib/stored";
import { Offline, Panel, Pill, SectionLabel } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "11:05" for a moment in the session, "24 Sep" for a daily close. */
function when(asOf: string): string {
  if (asOf.includes("T")) return asOf.slice(11, 16);
  const [, m, d] = asOf.split("-").map(Number);
  return m && d ? `${d} ${MONTHS[m - 1]}` : asOf;
}

const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v)}%`);
const VS: Record<Versus, string> = {
  more: "more often than other days", less: "less often than other days", like: "like other days", few: "too few days",
};

function History({ h, targets, ti, setTi, note }: {
  h: IndicatorHistory; targets: number[]; ti: number; setTi: (i: number) => void; note: string;
}) {
  const t = targets[ti];
  const rows = [["either", "Either way"], ["up", "Up from the open"], ["down", "Down from the open"]] as const;
  return (
    <section aria-label="When it read like this before" className="space-y-2 border-t border-zinc-800 pt-2.5">
      <h4 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-500">When it read like this before</h4>
      <p className="text-[11.5px] text-zinc-400">
        Sessions after a close in <span className="text-zinc-200">{h.bucket}</span>: {h.like.n.toLocaleString("en-IN")} of{" "}
        {h.all.n.toLocaleString("en-IN")}.
      </p>
      <label htmlFor="ind-target" className="flex items-center gap-2 text-[11.5px] text-zinc-400">
        <span className="shrink-0">Move I need</span>
        <input id="ind-target" type="range" min={0} max={targets.length - 1} step={1} value={ti}
          onChange={(e) => setTi(Number(e.target.value))}
          className="h-8 min-w-0 flex-1 accent-indigo-400" aria-valuetext={`${t} points`} />
        <span className="w-14 shrink-0 text-right font-mono tabular-nums text-zinc-100">{t} pts</span>
      </label>
      <table className="w-full text-[11.5px]">
        <thead className="text-[10px] uppercase tracking-[0.06em] text-zinc-500">
          <tr className="border-b border-zinc-800">
            <th className="py-1 pr-2 text-left font-medium">Next session went {t}+ pts</th>
            <th className="py-1 pr-2 text-right font-medium">After this</th>
            <th className="py-1 text-right font-medium">All days</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, label]) => (
            <tr key={k} className="border-b border-zinc-900">
              <td className="py-1 pr-2 text-zinc-400">{label}</td>
              <td className="py-1 pr-2 text-right font-mono tabular-nums text-zinc-100">{pct(h.like[k][ti])}</td>
              <td className="py-1 text-right font-mono tabular-nums text-zinc-400">{pct(h.all[k][ti])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11.5px] leading-relaxed text-zinc-400">
        {t}+ pts either way:{" "}
        <Pill tone={h.vs_rest.either[ti] === "more" ? "info" : "neutral"}>{VS[h.vs_rest.either[ti] ?? "few"]}</Pill>
        {" "}· typical biggest move from the open {h.like.median_either_pts ?? "–"} pts (all days {h.all.median_either_pts ?? "–"})
        {" "}· closed higher {pct(h.like.closed_up_pct)} (all days {pct(h.all.closed_up_pct)}),{" "}
        {VS[h.closed_up_vs_rest]}.
      </p>
      <p className="text-[10.5px] leading-snug text-zinc-500">{note}</p>
    </section>
  );
}

function Explainer({ t, data, ti, setTi }: { t: IndicatorTile; data: Indicators; ti: number; setTi: (i: number) => void }) {
  const parts = [["What it is", t.explain.what], ["Why traders watch it", t.explain.why],
                 ["How it reacts to the market", t.explain.reacts], ["For an option buyer", t.explain.buyer]] as const;
  return (
    <div className="space-y-2.5">
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-[12.5px] font-medium text-zinc-100">{t.name}</h3>
          <span className="font-mono text-[12px] tabular-nums text-zinc-300">{t.value}</span>
        </div>
        {t.now && <p className="mt-1 text-[12px] leading-relaxed text-zinc-200">{t.now}</p>}
      </div>
      <dl className="space-y-1.5">
        {parts.map(([k, v]) => (
          <div key={k}>
            <dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-500">{k}</dt>
            <dd className="text-[11.5px] leading-relaxed text-zinc-400">{v}</dd>
          </div>
        ))}
      </dl>
      {t.history ? (
        <History h={t.history} targets={data.targets} ti={ti} setTi={setTi} note={data.history_note} />
      ) : (
        <p className="border-t border-zinc-800 pt-2 text-[11px] text-zinc-500">No record of what followed this reading is available.</p>
      )}
    </div>
  );
}

/** In a session the server folds today's candle so far into every reading,
 *  and the page's AutoRefresh brings a new set each minute. No timer here
 *  (DESIGN §9): a card's own timer is how the open-interest card once froze.
 *
 *  Hovering a tile (or tapping it, or focusing it and pressing Enter) opens
 *  what the indicator is and what followed readings like today's. Hover opens
 *  it while the pointer is on the tile or the panel; a click pins it until
 *  Escape, the close button, or a click elsewhere. */
export function IndicatorGrid({ initial: data }: { initial: Indicators | null }) {
  const [open, setOpen] = useState<{ key: string; pinned: boolean } | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const [stored, store] = useStored("indicators.target", "100");
  const wrap = useRef<HTMLDivElement>(null);
  const tiles = useRef<Record<string, HTMLButtonElement | null>>({});
  const closing = useRef<ReturnType<typeof setTimeout> | null>(null);

  const found = data?.targets.indexOf(Number(stored)) ?? -1;
  const ti = found >= 0 ? found : Math.max(0, data?.targets.indexOf(100) ?? 0);
  const setTi = (i: number) => data && store(String(data.targets[i]));

  const place = useCallback((key: string) => {
    const el = tiles.current[key], box = wrap.current;
    if (!el || !box) return;
    const w = box.clientWidth, width = Math.min(420, w);
    const left = Math.min(Math.max(0, el.offsetLeft), w - width);
    setPos({ top: el.offsetTop + el.offsetHeight + 6, left, width });
  }, []);

  const show = (key: string, pinned: boolean) => {
    if (closing.current) clearTimeout(closing.current);
    if (open?.pinned && !pinned && open.key !== key) return;   // a pinned panel stays until closed
    place(key);
    setOpen({ key, pinned });
  };
  const leave = () => {
    if (open?.pinned) return;
    closing.current = setTimeout(() => setOpen(null), 150);
  };

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        const k = open.key;
        setOpen(null);
        tiles.current[k]?.focus();
      }
    };
    const away = (e: PointerEvent) => {
      if (open.pinned && wrap.current && !wrap.current.contains(e.target as Node)) setOpen(null);
    };
    const resize = () => place(open.key);
    window.addEventListener("keydown", esc);
    window.addEventListener("pointerdown", away);
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("keydown", esc);
      window.removeEventListener("pointerdown", away);
      window.removeEventListener("resize", resize);
    };
  }, [open, place]);

  const hint = data && (
    <>
      {data.basis}
      {data.live && <Pill tone="warn">provisional</Pill>}
      <span className="text-zinc-600">· hover or tap a tile to explain it</span>
    </>
  );
  const current = data && open ? data.tiles.find((t) => t.key === open.key) : null;

  return (
    <>
      <SectionLabel hint={hint}>Indicators</SectionLabel>
      {!data ? (
        <Offline what="Indicators" />
      ) : (
        <div ref={wrap} className="relative">
          {/* Columns follow the card's own width, not the window's: four where
              there is room for four, two on a phone or a narrow column. Every
              tile draws its top and left rule; the grid is pulled up and left by
              a pixel so the outer ones fall under the panel's own border. */}
          <Panel className="@container overflow-hidden">
            <div className="-ml-px -mt-px grid grid-cols-2 @2xl:grid-cols-4">
              {data.tiles.map((t) => {
                const active = open?.key === t.key;
                return (
                  <button key={t.key} id={`ind-${t.key}`} type="button"
                    ref={(el) => { tiles.current[t.key] = el; }}
                    aria-expanded={active} aria-controls="ind-explainer"
                    onMouseEnter={() => show(t.key, false)} onMouseLeave={leave}
                    onClick={() => (active && open?.pinned ? setOpen(null) : show(t.key, true))}
                    className={`flex min-w-0 flex-col border-l border-t border-zinc-800/70 px-3.5 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500/60 focus-visible:outline-none ${
                      active ? "bg-zinc-800/50" : "hover:bg-zinc-900/70"}`}>
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="min-w-0 truncate text-[11px] text-zinc-500">
                        {t.name} <span aria-hidden className="text-zinc-600">ⓘ</span>
                      </span>
                      {/* Only a reading from another moment than the header's carries its own time. */}
                      {t.as_of !== data.as_of && (
                        <span className="shrink-0 font-mono text-[10px] tabular-nums text-zinc-600">{when(t.as_of)}</span>
                      )}
                    </span>
                    <span className="mt-1 font-mono text-sm font-medium leading-snug tabular-nums text-zinc-100">
                      {t.value}
                    </span>
                    <span className="text-[11px] leading-snug text-zinc-400">{t.state || " "}</span>
                    <span className="mt-1.5 text-[10.5px] leading-snug text-zinc-500">{t.detail}</span>
                  </button>
                );
              })}
            </div>
          </Panel>
          {current && pos && (
            <div id="ind-explainer" role="dialog" aria-label={`${current.name} explained`}
              onMouseEnter={() => closing.current && clearTimeout(closing.current)} onMouseLeave={leave}
              style={{ top: pos.top, left: pos.left, width: pos.width }}
              className="absolute z-30 max-h-[70vh] overflow-y-auto rounded-xl border border-zinc-700/70 bg-zinc-950/95 p-3.5 shadow-xl shadow-black/40 backdrop-blur">
              {open?.pinned && (
                <button id="ind-explainer-close" type="button" onClick={() => setOpen(null)} aria-label="Close"
                  className="float-right -mr-1 -mt-1 ml-2 min-h-8 min-w-8 rounded-md text-zinc-500 hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:outline-none">
                  ✕
                </button>
              )}
              <Explainer t={current} data={data} ti={ti} setTi={setTi} />
            </div>
          )}
        </div>
      )}
    </>
  );
}
