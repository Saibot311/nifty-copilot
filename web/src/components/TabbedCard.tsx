"use client";

import { useId, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";
import { SectionLabel } from "./ui";

const CHANGED = "tabs-changed";

export type TabSpec = {
  id: string;
  label: string;
  /** Shown beside the group heading while this tab is open. */
  hint?: ReactNode;
  /** The freshness check's reason this tab's data is behind, if it is. */
  behind?: string | null;
  content: ReactNode;
};

/** One heading, a row of tabs, and the open tab's card. Only the open tab is
 *  mounted, so a card never measures itself while hidden. The server renders
 *  the first tab; the browser then restores the one last chosen (localStorage,
 *  per `storageKey`). Arrow keys, Home and End move between tabs. */
export function Tabs({ title, tabs, storageKey }: { title: string; tabs: TabSpec[]; storageKey: string }) {
  const uid = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const key = `tabs:${storageKey}`;
  // The server and the first client render show the first tab; then the remembered one.
  const saved = useSyncExternalStore(
    (cb) => {
      window.addEventListener(CHANGED, cb);
      window.addEventListener("storage", cb);
      return () => {
        window.removeEventListener(CHANGED, cb);
        window.removeEventListener("storage", cb);
      };
    },
    () => {
      try {
        return localStorage.getItem(key);
      } catch {
        return null; // storage blocked: stay on the first tab
      }
    },
    () => null,
  );
  const [picked, setPicked] = useState<string | null>(null);
  const active = picked ?? saved;

  const choose = (id: string, focus = false) => {
    setPicked(id);
    try {
      localStorage.setItem(key, id);
      window.dispatchEvent(new Event(CHANGED));
    } catch {
      /* not remembered */
    }
    if (focus) refs.current[id]?.focus();
  };

  const onKey = (e: KeyboardEvent, i: number) => {
    const last = tabs.length - 1;
    const to =
      e.key === "ArrowRight" || e.key === "ArrowDown" ? (i === last ? 0 : i + 1)
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (i === 0 ? last : i - 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : -1;
    if (to < 0) return;
    e.preventDefault();
    choose(tabs[to].id, true);
  };

  const cur = tabs.find((t) => t.id === active) ?? tabs[0];
  if (!cur) return null;
  return (
    <div className="min-w-0">
      <SectionLabel hint={cur.hint} behind={cur.behind}>{title}</SectionLabel>
      <div role="tablist" aria-label={title} className="mb-3 flex gap-1 overflow-x-auto border-b border-zinc-800/80">
        {tabs.map((t, i) => {
          const on = t.id === cur.id;
          return (
            <button
              key={t.id}
              ref={(el) => { refs.current[t.id] = el; }}
              type="button"
              role="tab"
              id={`${uid}-tab-${t.id}`}
              aria-selected={on}
              aria-controls={`${uid}-panel-${t.id}`}
              tabIndex={on ? 0 : -1}
              onClick={() => choose(t.id)}
              onKeyDown={(e) => onKey(e, i)}
              className={`-mb-px min-h-10 shrink-0 whitespace-nowrap border-b-2 px-3 text-[12px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 ${
                on ? "border-indigo-400 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${uid}-panel-${cur.id}`}
        aria-labelledby={`${uid}-tab-${cur.id}`}
        tabIndex={0}
        className="min-w-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60"
      >
        {cur.content}
      </div>
    </div>
  );
}
