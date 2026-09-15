"use client";

import { useState, type ReactNode } from "react";

const TABS = [
  { id: "today", label: "Today", hint: "What the market is doing now" },
  { id: "research", label: "Research", hint: "What the historical record says" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function DashboardTabs({ today, research }: { today: ReactNode; research: ReactNode }) {
  const [active, setActive] = useState<TabId>("today");

  return (
    <div className="flex flex-col gap-6">
      <div
        role="tablist"
        aria-label="Dashboard sections"
        className="flex items-center gap-1 border-b border-zinc-800"
      >
        {TABS.map((tab) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              id={`tab-${tab.id}`}
              role="tab"
              aria-selected={selected}
              aria-controls={`panel-${tab.id}`}
              onClick={() => setActive(tab.id)}
              title={tab.hint}
              className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 ${
                selected
                  ? "border-indigo-400 text-zinc-100"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        id="panel-today"
        role="tabpanel"
        aria-labelledby="tab-today"
        hidden={active !== "today"}
        className="flex flex-col gap-7"
      >
        {today}
      </div>
      <div
        id="panel-research"
        role="tabpanel"
        aria-labelledby="tab-research"
        hidden={active !== "research"}
        className="flex flex-col gap-7"
      >
        {research}
      </div>
    </div>
  );
}
