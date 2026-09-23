import type { ReactNode } from "react";

/** Shared primitives so hierarchy is expressed deliberately rather than
 *  every block being an identical card. Weight is spent by role:
 *  `emphasis` lifts the one thing that matters on a screen, `plain` is for
 *  supporting detail that shouldn't compete with it. */

export function Panel({
  children,
  emphasis = "plain",
  className = "",
}: {
  children: ReactNode;
  emphasis?: "plain" | "raised" | "accent";
  className?: string;
}) {
  const styles = {
    plain: "border-zinc-800/80 bg-zinc-900/40",
    raised: "border-zinc-700/70 bg-zinc-900/80 shadow-lg shadow-black/20",
    accent: "border-indigo-500/30 bg-indigo-500/[0.04]",
  }[emphasis];
  return <div className={`rounded-xl border ${styles} ${className}`}>{children}</div>;
}

export function SectionLabel({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        {children}
      </h2>
      {hint && <span className="text-[11px] text-zinc-600">{hint}</span>}
    </div>
  );
}

export function Stat({
  label,
  value,
  tone = "neutral",
  sub,
}: {
  label: string;
  value: ReactNode;
  tone?: "good" | "bad" | "neutral" | "muted";
  sub?: string;
}) {
  const color = {
    good: "text-emerald-400",
    bad: "text-rose-400",
    neutral: "text-zinc-100",
    muted: "text-zinc-400",
  }[tone];
  return (
    <div className="min-w-0">
      <div className="truncate text-[11px] text-zinc-500">{label}</div>
      <div className={`font-mono text-sm font-medium tabular-nums ${color}`}>{value}</div>
      {sub && <div className="truncate text-[10px] text-zinc-600">{sub}</div>}
    </div>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "good" | "bad" | "warn" | "neutral" | "info";
}) {
  const styles = {
    good: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    bad: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    info: "border-indigo-500/30 bg-indigo-500/10 text-indigo-300",
    neutral: "border-zinc-700 bg-zinc-800/60 text-zinc-300",
  }[tone];
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${styles}`}
    >
      {children}
    </span>
  );
}

/** What a card shows instead of a number it does not have. Never a zero, never
 *  a dash pretending to be a value. The command is the one that is true now:
 *  since Phase 15 the API runs as a service, so "start the dev server" was an
 *  instruction that would not have helped. */
export function Offline({ what, why }: { what: string; why?: string }) {
  return (
    <Panel className="p-4">
      <div className="text-sm text-zinc-400">{what} is not available.</div>
      <div className="mt-1 text-xs text-zinc-500">
        {why ?? "The API did not answer. Check the service, then reload."}
      </div>
      <code className="mt-2 block rounded bg-black/40 px-2 py-1 text-[11px] text-zinc-500">
        ./scripts/install_app_services.sh --status
      </code>
    </Panel>
  );
}

/** A signed percentage. toFixed() emits a hyphen; DESIGN.md §4 wants a real
 *  minus (U+2212), and this is the one place every card gets it from. */
export function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return "–";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

export function fmtNum(v: number | null | undefined) {
  if (v == null) return "–";
  return v.toLocaleString("en-IN");
}
