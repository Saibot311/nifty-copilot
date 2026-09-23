"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

const TABS = [
  { id: "today", label: "Today", hint: "What would change your next action" },
  { id: "research", label: "Research", hint: "What the record says" },
  { id: "market", label: "Market", hint: "How this market works, and who is on the other side" },
  { id: "journal", label: "Journal", hint: "What you did, and what the paper book did" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function isTab(value: string | null): value is TabId {
  return !!value && TABS.some((t) => t.id === value);
}

export function DashboardTabs({ today, research, market, journal }: {
  today: ReactNode; research: ReactNode; market: ReactNode; journal: ReactNode;
}) {
  const [active, setActive] = useState<TabId>("today");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  // The open tab lives in the URL: a reload keeps it, and a view can be sent
  // to yourself. replaceState rather than push, so Back leaves the page
  // instead of walking the tabs.
  useEffect(() => {
    // After hydration, not during it: the server rendered "today", and
    // setting state synchronously here would make the first client render
    // disagree with the markup it was given.
    const id = window.setTimeout(() => {
      const fromUrl = new URLSearchParams(window.location.search).get("tab");
      if (isTab(fromUrl)) setActive(fromUrl);
    }, 0);
    return () => window.clearTimeout(id);
  }, []);

  const select = (id: TabId) => {
    setActive(id);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", id);
      window.history.replaceState({}, "", url.toString());
    } catch {
      // A browser that refuses history is not a reason to break the tabs.
    }
  };

  // The ARIA tabs pattern this markup claims: arrows move, Home and End jump.
  const onKeyDown = (e: React.KeyboardEvent, index: number) => {
    const keys: Record<string, number> = {
      ArrowRight: (index + 1) % TABS.length,
      ArrowLeft: (index - 1 + TABS.length) % TABS.length,
      Home: 0,
      End: TABS.length - 1,
    };
    const next = keys[e.key];
    if (next === undefined) return;
    e.preventDefault();
    select(TABS[next].id);
    buttons.current[next]?.focus();
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Pinned to the bottom on a phone, where the thumb is; in the flow on
          anything larger. */}
      <div
        role="tablist"
        aria-label="Dashboard sections"
        className="fixed inset-x-0 bottom-0 z-20 flex items-center justify-around gap-1 border-t border-zinc-800 bg-zinc-950/95 px-2 pb-[env(safe-area-inset-bottom,0px)] backdrop-blur sm:static sm:justify-start sm:border-t-0 sm:border-b sm:bg-transparent sm:px-0 sm:pb-0 sm:backdrop-blur-none"
      >
        {TABS.map((tab, i) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              id={`tab-${tab.id}`}
              ref={(el) => { buttons.current[i] = el; }}
              role="tab"
              aria-selected={selected}
              aria-controls={`panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => select(tab.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              title={tab.hint}
              className={`px-4 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 sm:-mb-px sm:border-b-2 sm:py-2.5 ${
                selected
                  ? "text-zinc-100 sm:border-indigo-400"
                  : "text-zinc-500 hover:text-zinc-300 sm:border-transparent"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {TABS.map((tab) => (
        <div
          key={tab.id}
          id={`panel-${tab.id}`}
          role="tabpanel"
          aria-labelledby={`tab-${tab.id}`}
          hidden={tab.id !== active}
          className="flex flex-col gap-7 pb-16 sm:pb-0"
        >
          {{ today, research, market, journal }[tab.id]}
        </div>
      ))}
    </div>
  );
}
