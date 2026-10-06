"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { subscribeToTick } from "@/lib/api";

/** Re-fetches the whole page on a timer.
 *
 *  The dashboard is server-rendered, so without this every section keeps
 *  whatever it was given when the tab was opened — patterns, indicators, the
 *  briefing and the market tab all freeze at page-load time. The header
 *  ticks on its own (LiveTicker); this refreshes the rest.
 *
 *  Every 60s while the market is open, every 15 minutes when it is shut, and
 *  never while the tab is in the background. */
export function AutoRefresh() {
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    let open: boolean | null = null;
    // A refresh that does not land — the server running a build replaced
    // under it (6 Oct 2026), or a request that fails — left a tab frozen
    // with nothing saying so. The page stamps every render; two refreshes in
    // a row that leave the stamp unchanged reload the tab.
    let misses = 0;
    const stamp = () => (document.getElementById("page-rendered-at") as HTMLTimeElement | null)?.dateTime;
    const tick = () => {
      if (!alive) return;
      if (document.visibilityState === "visible") {
        const before = stamp();
        router.refresh();
        setTimeout(() => {
          if (!alive || document.visibilityState !== "visible") return;
          misses = stamp() === before ? misses + 1 : 0;
          if (misses >= 2) window.location.reload();
        }, 20_000);
      }
      timer = setTimeout(tick, open ? 60_000 : 900_000);
    };

    // Market state comes from the shared tick rather than a fetch of its own.
    // When it turns open, refresh now: waiting out the 15-minute shut-market
    // timer left the page on the pre-open picture until as late as 09:30.
    const stop = subscribeToTick((t) => {
      const now = !!(t.market?.is_open ?? t.market?.open_by_clock);
      const opened = open === false && now;
      open = now;
      if (opened) { clearTimeout(timer); tick(); }
    });

    timer = setTimeout(tick, 60_000);
    return () => { alive = false; clearTimeout(timer); stop(); };
  }, [router]);

  return null;
}
