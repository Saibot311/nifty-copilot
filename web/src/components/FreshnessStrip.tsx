import type { Freshness } from "@/lib/api";

/** One line under the header: every card current, or which are behind and why.
 *  The watchdog checks every ten minutes (scripts/freshness_check.py) and
 *  fixes what it can; this only reports. Before it existed a card could sit
 *  days behind (5-6 Oct 2026) with nothing on the page saying so. */
export function FreshnessStrip({ data }: { data: Freshness | null }) {
  if (!data) {
    return <p className="mb-4 text-[11px] text-zinc-600">Freshness: no check yet — the watchdog runs one every ten minutes.</p>;
  }
  const checked = data.checked_at.slice(11, 16);
  const late = data.check_age_min != null && data.check_age_min > 25;
  const behind = data.sources.filter((s) => s.status === "behind");
  const unavailable = data.sources.filter((s) => s.status === "unavailable");
  const services = data.services.filter((s) => s.behind);
  const ok = !behind.length && !unavailable.length && !services.length && !late;
  if (ok) {
    return (
      <p className="mb-4 text-[11px] text-zinc-600">
        All {data.current} live and daily sources current · checked {checked} IST
        {data.on_demand > 0 && ` · ${data.on_demand} on-demand studies shown with their age`}
      </p>
    );
  }
  return (
    <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/[0.05] px-3 py-2 text-[12px] text-amber-200">
      <p>
        {behind.length > 0 && `${behind.length} card${behind.length === 1 ? "" : "s"} behind`}
        {behind.length > 0 && unavailable.length > 0 && " · "}
        {unavailable.length > 0 && `${unavailable.length} not answering`}
        {late && `${behind.length || unavailable.length ? " · " : ""}the check itself last ran ${Math.round(data.check_age_min!)} min ago`}
        <span className="text-amber-200/70"> · checked {checked} IST{data.nightly_job_running && " · nightly job running, fixes wait for it"}</span>
      </p>
      <ul className="mt-1 list-disc pl-4 text-[11px] text-amber-200/80">
        {[...behind, ...unavailable].map((s) => (
          <li key={s.key}><span className="text-amber-200">{s.card}</span>: {s.reason}{s.fix.length > 0 && " — the watchdog is fixing it"}</li>
        ))}
        {services.map((s) => (
          <li key={s.service}>{s.service.split(".").pop()} is running older code than is on disk — {s.action}</li>
        ))}
      </ul>
    </div>
  );
}
